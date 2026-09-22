"""Кабінет ДПС без ключа КЕП на сервері (#324).

Покриття:
- у моделі немає ні поля ключа, ні шляхів до нативної бібліотеки, ні майстра
  пароля;
- кожен запит до API кабінету несе підпис, отриманий із браузера, а без
  підпису не йде взагалі;
- перевірка з'єднання, синхронізація, підпис, подання і повторне завантаження
  файлів документа проходять через діалог l10n_ua.sign.mixin.
"""

import base64
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

CONFIG_MODULE = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config'
CONFIG_CLASS = CONFIG_MODULE + '.L10nUaTaxCabinetConfig'
AUTH = 'AUTH-SIGNATURE=='
XML = base64.b64encode(b'<?xml version="1.0" encoding="UTF-8"?><DECLAR/>').decode()


def _json_response(payload, status=200):
    response = MagicMock(status_code=status, text=str(payload))
    response.json.return_value = payload
    return response


@tagged('post_install', '-at_install')
class TestCabinetBrowserSigning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # UNIQUE(company_id) — переуживаємо наявний рядок, якщо він є.
        Config = cls.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False)
        cls.config = Config.search([('company_id', '=', cls.company.id)], limit=1)
        vals = {'name': 'Кабінет (тест підпису)', 'taxpayer_code': '1234567890',
                'active': True, 'auto_download_pdf': False, 'auto_download_xml': False}
        if cls.config:
            cls.config.write(vals)
        else:
            cls.config = Config.create({**vals, 'company_id': cls.company.id})
        cls.doc_type = cls.env.ref('l10n_ua_tax.tax_document_type_ep_declaration')

    def _document(self, **vals):
        return self.env['l10n_ua.tax.document'].create({
            'name': 'Декларація ЄП',
            'document_type_id': self.doc_type.id,
            'company_id': self.company.id,
            'taxpayer_code': '1234567890',
            'file_xml': XML,
            'file_xml_name': 'F0103309.xml',
            **vals,
        })

    # --- модель ---

    def test_no_key_storage_on_server(self):
        fields = self.env['l10n_ua.tax.cabinet.config']._fields
        for name in ('kep_key_file', 'kep_key_filename', 'iit_lib_path', 'iit_cert_path'):
            self.assertNotIn(name, fields)
        self.assertNotIn('l10n_ua.tax.cabinet.password.wizard', self.env)

    def test_api_refuses_without_signature(self):
        with patch(CONFIG_MODULE + '.requests.get') as get:
            for empty in (None, '', b''):
                with self.assertRaises(UserError):
                    self.config._api_get_document_list(2026, 3, auth_signature=empty)
            get.assert_not_called()

    # --- перевірка з'єднання ---

    def test_connection_check_signs_taxpayer_code_in_browser(self):
        action = self.config.action_test_connection()
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params']['mode'], 'test')

        spec = self.config.kep_prepare_signing()
        self.assertEqual(spec['auth_subject'], '1234567890')
        self.assertEqual(spec['documents'], [])

        payer = [{'values': {'FULL_NAME': 'ФОП Тестовий'}}]
        with patch(CONFIG_MODULE + '.requests.get', return_value=_json_response(payer)) as get:
            result = self.config.kep_submit_signed({}, AUTH)
        self.assertIn('ФОП Тестовий', result['receipt'])
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], AUTH)

    # --- синхронізація ---

    def test_sync_uses_signature_from_browser(self):
        wizard = self.env['l10n_ua.tax.cabinet.sync.wizard'].create({
            'mode': 'sync', 'config_id': self.config.id, 'company_id': self.company.id,
            'sync_type': 'reported', 'year': 2026, 'month': '3',
        })
        action = wizard.action_process()
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params']['mode'], 'sync')

        spec = wizard.kep_prepare_signing()
        self.assertEqual(spec['auth_subject'], '1234567890')
        self.assertEqual(spec['close_action']['res_model'], 'l10n_ua.tax.document')

        listing = [{'codRegdoc': 777001, 'docName': 'Декларація ЄП', 'doc': 'F0103309',
                    'dget': '2026-04-10 12:00:00', 'periodYear': 2026, 'periodMonth': 3}]
        with patch(CONFIG_MODULE + '.requests.get', return_value=_json_response(listing)) as get:
            result = wizard.kep_submit_signed({}, AUTH)

        self.assertIn('1', result['receipt'])
        self.assertEqual(get.call_args.kwargs['params'], {'periodYear': 2026, 'periodMonth': 3})
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], AUTH)
        doc = self.env['l10n_ua.tax.document'].search([('external_id', '=', '777001')])
        self.assertEqual(doc.source, 'cabinet')
        self.assertTrue(self.config.last_sync_date)

    # --- документ ---

    def test_sign_mode_stores_p7s_signed_in_browser(self):
        doc = self._document()
        action = doc.action_sign_document()
        self.assertEqual(action['params']['mode'], 'sign')

        signing = doc.with_context(kep_mode='sign')
        spec = signing.kep_prepare_signing()
        self.assertFalse(spec['auth_subject'])
        self.assertEqual(spec['documents'][0]['format'], 'cades')
        self.assertEqual(spec["documents"][0]["data_b64"], XML)

        signing.kep_submit_signed({'doc': 'UDdTLVNJR05BVFVSRQ=='})
        self.assertEqual(doc.state, 'signed')
        self.assertEqual(doc.file_signed_name, 'F0103309.p7s')
        self.assertEqual(doc.file_signed.content, b'P7S-SIGNATURE')

    def test_submit_mode_relays_envelope_and_auth(self):
        doc = self._document()
        action = doc.action_submit_to_cabinet()
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertNotIn('mode', action['params'])

        with patch(CONFIG_CLASS + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = doc.kep_prepare_signing()
        self.assertEqual(spec['auth_subject'], '1234567890')
        self.assertEqual(spec['documents'][0]['format'], 'envelope')
        self.assertEqual(spec['documents'][0]['recipient_cert_b64'],
                         base64.b64encode(b'CERT').decode())

        with patch(CONFIG_CLASS + '._api_submit_document_presigned',
                   return_value={'message': 'Квитанція №1'}) as submit:
            doc.kep_submit_signed({'doc': 'ENVELOPE=='}, AUTH)
        submit.assert_called_once_with('ENVELOPE==', 'F0103309.xml', AUTH)
        self.assertEqual(doc.state, 'submitted')
        self.assertEqual(doc.status_message, 'Квитанція №1')

    def test_redownload_mode_needs_only_auth_signature(self):
        doc = self._document(source='cabinet', external_id='555', file_xml=False,
                             file_xml_name=False)
        action = doc.action_redownload_files()
        self.assertEqual(action['params']['mode'], 'redownload')

        downloading = doc.with_context(kep_mode='redownload')
        spec = downloading.kep_prepare_signing()
        self.assertEqual(spec['auth_subject'], '1234567890')
        self.assertEqual(spec['documents'], [])

        with patch(CONFIG_CLASS + '._api_download_document_xml', return_value=XML) as xml, \
                patch(CONFIG_CLASS + '._api_download_document_pdf', return_value=None):
            result = downloading.kep_submit_signed({}, AUTH)
        self.assertEqual(xml.call_args.kwargs['auth_signature'], AUTH)
        self.assertIn('XML', result['receipt'])
        self.assertEqual(doc.file_xml_name, '555.xml')

    def test_redownload_rejected_for_manual_documents(self):
        with self.assertRaises(UserError):
            self._document().action_redownload_files()
