"""Тести реальної реєстрації в ЄРПН через клієнтське КЕП-підписування (#146).

Підпис відбувається в браузері (euscp), тож серверні тести покривають:
- відмову без налаштованого кабінету (жодного фейкового статусу);
- відкриття клієнтського віджета підпису без зміни стану;
- підготовку даних для браузера (erpn_prepare_signing);
- релей підписаного конверта й фіксацію квитанції (erpn_submit_signed),
  з моком API кабінету — успіх і помилка.
"""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

CONFIG = 'l10n_ua.tax.cabinet.config'
CONFIG_PATH = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'


@tagged('post_install', '-at_install')
class TestErpnRegister(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Покупець ЄРПН'})
        cls.company.write({
            'l10n_ua_is_vat_payer': True,
            'l10n_ua_vat_ipn': '123456789012',
        })
        # Прибрати сторонні активні конфіги кабінету цієї компанії — детермінізм.
        cls.env[CONFIG].search([('company_id', '=', cls.company.id)]).write(
            {'active': False})

    def _invoice(self, **kwargs):
        vals = {
            'doc_type': 'pn', 'number': 'ЄРПН-1', 'date': date(2025, 6, 10),
            'invoice_type': 'issued', 'partner_id': self.partner.id,
            'company_id': self.company.id,
            'line_ids': [(0, 0, {
                'name': 'Послуги', 'quantity': 1, 'price_unit': 10000,
                'vat_rate': '20', 'dkpp_code': '62.01.11-00.00'})],
        }
        vals.update(kwargs)
        return self.env['l10n_ua.tax.invoice'].create(vals)

    def _config(self):
        # UNIQUE(company_id): переуживаємо наявний рядок (навіть неактивний),
        # інакше створюємо. Так тест стабільний і на заповненій dev-БД.
        cfg = self.env[CONFIG].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет тест', 'taxpayer_code': '12345678',
                'active': True}
        if cfg:
            cfg.write(vals)
            return cfg
        return self.env[CONFIG].create({**vals, 'company_id': self.company.id})

    # --- Без конфігурації: жодного фейку ---

    def test_register_without_config_raises(self):
        inv = self._invoice()
        with self.assertRaises(UserError):
            inv.action_register_erpn()
        self.assertEqual(inv.state, 'draft')  # статус НЕ змінився

    # --- Відкриття віджета підпису ---

    def test_register_opens_sign_widget(self):
        self._config()
        inv = self._invoice()
        action = inv.action_register_erpn()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params'], {
            'model': 'l10n_ua.tax.invoice', 'res_id': inv.id})
        self.assertEqual(inv.state, 'draft')  # ще не зареєстровано
        self.assertTrue(inv.file_xml)  # XML згенеровано

    def test_register_non_draft_raises(self):
        self._config()
        inv = self._invoice()
        inv.state = 'registered'
        with self.assertRaises(UserError):
            inv.action_register_erpn()

    # --- Підготовка даних для браузера (контракт sign.mixin) ---

    def test_prepare_signing_payload(self):
        self._config()
        inv = self._invoice()
        with patch(CONFIG_PATH + '._get_dps_encrypt_certificate',
                   return_value=b'FAKE-DPS-CERT'):
            data = inv.kep_prepare_signing()
        self.assertEqual(data['auth_subject'], '12345678')
        self.assertEqual(len(data['documents']), 1)
        doc = data['documents'][0]
        self.assertEqual(doc['name'], 'doc')
        self.assertEqual(doc['format'], 'envelope')
        self.assertTrue(doc['data_b64'])
        self.assertTrue(doc['recipient_cert_b64'])
        self.assertTrue(doc['filename'].endswith('.xml'))
        # data_b64 має декодуватись у валідний XML податкової накладної.
        import base64
        xml = base64.b64decode(doc['data_b64']).decode('windows-1251')
        self.assertIn('<?xml', xml)

    # --- Релей підписаного конверта ---

    def test_submit_signed_success(self):
        self._config()
        inv = self._invoice()
        inv.action_generate_xml()  # щоб _generate_xml_filename був детермінований
        with patch(CONFIG_PATH + '._api_submit_document_presigned',
                   return_value={'message': 'Квитанція №1: прийнято'}) as m:
            res = inv.kep_submit_signed({'doc': 'ENVELOPE=='}, 'AUTHSIG==')
        # Релей: (конверт, ім'я файлу, auth-підпис). Ім'я рахує сервер.
        args = m.call_args.args
        self.assertEqual(args[0], 'ENVELOPE==')
        self.assertEqual(args[2], 'AUTHSIG==')
        self.assertTrue(args[1].endswith('.xml'))
        self.assertEqual(inv.state, 'registered')
        self.assertIn('прийнято', inv.erpn_receipt)
        self.assertTrue(inv.erpn_date)
        self.assertEqual(res['receipt'], 'Квитанція №1: прийнято')

    def test_submit_signed_failure_keeps_draft(self):
        self._config()
        inv = self._invoice()
        with patch(CONFIG_PATH + '._api_submit_document_presigned',
                   side_effect=UserError('Відхилено ДПС')):
            with self.assertRaises(UserError):
                inv.kep_submit_signed({'doc': 'ENVELOPE=='}, 'AUTHSIG==')
        self.assertEqual(inv.state, 'draft')  # не зареєстровано на помилці

    def test_submit_signed_non_draft_raises(self):
        self._config()
        inv = self._invoice()
        inv.state = 'cancelled'
        with self.assertRaises(UserError):
            inv.kep_submit_signed({'doc': 'E'}, 'A')

    def test_submit_signed_missing_signature_raises(self):
        self._config()
        inv = self._invoice()
        with self.assertRaises(UserError):
            inv.kep_submit_signed({}, 'AUTHSIG==')  # немає підпису 'doc'


@tagged('post_install', '-at_install')
class TestPresignedRelay(TransactionCase):
    """HTTP-релей _api_submit_document_presigned без ключа/пароля."""

    def _config(self):
        cfg = self.env[CONFIG].with_context(active_test=False).search(
            [('company_id', '=', self.env.company.id)], limit=1)
        vals = {'name': 'Реле тест', 'taxpayer_code': '12345678',
                'active': True}
        if cfg:
            cfg.write(vals)
            return cfg
        return self.env[CONFIG].create(
            {**vals, 'company_id': self.env.company.id})

    def test_presigned_posts_with_client_auth_header(self):
        config = self._config()

        class FakeResp:
            status_code = 200
            text = '{"message": "ok"}'
            headers = {}

            def json(self):
                return {'message': 'ok'}

        with patch('odoo.addons.l10n_ua_tax_cabinet.models.'
                   'l10n_ua_tax_cabinet_config.requests.post',
                   return_value=FakeResp()) as post:
            result = config._api_submit_document_presigned(
                'ENVB64', 'F1201.xml', 'CLIENT-AUTH-SIG')

        self.assertEqual(result['message'], 'ok')
        _args, kwargs = post.call_args
        # Заголовок Authorization = переданий клієнтський підпис (сервер не підписує).
        self.assertEqual(kwargs['headers']['Authorization'], 'CLIENT-AUTH-SIG')
        # Тіло у форматі API кабінету.
        self.assertEqual(
            kwargs['json']['list'][0]['contentBase64'], 'ENVB64')
        self.assertEqual(kwargs['json']['list'][0]['fname'], 'F1201.xml')
