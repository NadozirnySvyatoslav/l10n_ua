"""XML фінзвітності за схемами ДПС і подання (#455, #456).

Кожен документ перевіряється офіційною XSD уже під час формування
(``_fin_dps_render``), тож тест «сформувалось» — це й тест валідності.
Дати — 2046 рік, як у тестах l10n_ua_accounting.
"""
import base64
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ua_accounting.tests.common import AccountingTestCase

CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'
Y = 2046


@tagged('post_install', '-at_install', 'l10n_ua_fin_report_dps')
class TestFinReportDps(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        office = cls.env['l10n_ua.tax.office'].create({'code': '2650', 'name': 'ГУ ДПС у м. Києві'})
        cls.company.write({
            'edrpou': '12345678', 'tax_office_code': '2650',
            'l10n_ua_tax_office_id': office.id, 'koatuu': '8038900000',
            'kved_main': '62.01', 'zip': '01001', 'city': 'Київ',
            'street': 'вул. Хрещатик, 1', 'phone': '044 123-45-67',
        })
        cls.company.partner_id.write({
            'l10n_ua_chief_name': 'Петренко Іван Іванович',
            'l10n_ua_accountant_name': 'Коваль Ольга Петрівна',
        })
        acc = cls._account
        cls.acc_40 = acc('40', 'Зареєстрований капітал', 'equity')
        cls.acc_311 = acc('311', 'Рахунок у банку', 'asset_cash')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')
        cls._entry(cls.acc_311, cls.acc_40, 150000.0, date(Y, 1, 15))
        cls._entry(cls.acc_361, cls.acc_702, 240000.0, date(Y, 2, 10))
        cls._entry(cls.acc_92, cls.acc_311, 36000.0, date(Y, 2, 20))
        cls._entry(cls.acc_311, cls.acc_361, 200000.0, date(Y, 3, 5))

    @classmethod
    def _account(cls, code, name, account_type, reconcile=False):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code, 'name': name, 'account_type': account_type,
            'reconcile': reconcile, 'company_ids': [(6, 0, cls.company.ids)],
        })

    @classmethod
    def _entry(cls, debit, credit, amount, on_date):
        move = cls.env['account.move'].create({
            'move_type': 'entry', 'journal_id': cls.misc_journal.id, 'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': debit.id, 'debit': amount, 'partner_id': cls.partner.id}),
                (0, 0, {'account_id': credit.id, 'credit': amount, 'partner_id': cls.partner.id}),
            ],
        })
        move.action_post()

    def _confirmed(self, model, **vals):
        report = self.env[model].create({'company_id': self.company.id, **vals})
        report.action_compute()
        report.action_confirm()
        return report

    def _xml(self, report):
        report.action_generate_dps_xml()
        return etree.fromstring(base64.b64decode(report.xml_file))

    def _year(self, model, **vals):
        return self._confirmed(model, date_from=date(Y, 1, 1), date_to=date(Y, 12, 31), **vals)

    # ---------------------------------------------------------------- форми

    def test_balance_year(self):
        report = self._confirmed('l10n_ua.balance.report', date_to=date(Y, 12, 31))
        root = self._xml(report)
        head, body = root.find('DECLARHEAD'), root.find('DECLARBODY')
        self.assertEqual(head.findtext('C_DOC') + head.findtext('C_DOC_SUB'), 'J09001')
        self.assertEqual((head.findtext('PERIOD_TYPE'), head.findtext('PERIOD_MONTH')), ('5', '12'))
        self.assertEqual(head.findtext('C_STI_ORIG'), '2650')
        self.assertEqual(body.findtext('HPERIOD'), '31 грудня')
        self.assertEqual(body.findtext('HZY'), str(Y))
        self.assertEqual(body.findtext('H01'), '1')
        self.assertEqual(body.findtext('HKOATUU'), '8038900000')
        self.assertEqual(body.findtext('HBOS'), 'Петренко Іван Іванович')
        # 150 + 240 − 36 = 354 тис. грн активів на кінець року.
        self.assertEqual(body.findtext('R1300G4'), '354')
        self.assertEqual(body.findtext('R1900G4'), '354')
        self.assertTrue(report.xml_filename.startswith('2650'))
        self.assertIn('J0900108', report.xml_filename)

    def test_balance_quarter(self):
        report = self._confirmed('l10n_ua.balance.report', date_to=date(Y, 3, 31))
        head = self._xml(report).find('DECLARHEAD')
        self.assertEqual((head.findtext('PERIOD_TYPE'), head.findtext('PERIOD_MONTH')), ('2', '3'))
        self.assertEqual(self._xml(report).find('DECLARBODY').findtext('HPERIOD'), '31 березня')

    def test_pnl_half_year(self):
        report = self._confirmed('l10n_ua.pnl.report', date_from=date(Y, 1, 1),
                                 date_to=date(Y, 6, 30))
        root = self._xml(report)
        self.assertEqual(root.find('DECLARHEAD').findtext('PERIOD_TYPE'), '3')
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('HPERIOD'), 'I півріччя')
        self.assertEqual(body.findtext('R2000G3'), '240')
        self.assertIsNone(body.find('HKOATUU'))

    def test_cashflow_both_methods(self):
        direct = self._year('l10n_ua.cashflow.report', method='direct')
        self.assertEqual(self._xml(direct).find('DECLARHEAD').findtext('C_DOC_SUB'), '009')
        indirect = self._year('l10n_ua.cashflow.report', method='indirect')
        self.assertEqual(self._xml(indirect).find('DECLARHEAD').findtext('C_DOC_SUB'), '016')

    def test_equity(self):
        report = self._year('l10n_ua.equity.report')
        self.assertEqual(self._xml(report).find('DECLARHEAD').findtext('C_DOC_SUB'), '010')

    def test_small_and_micro(self):
        for kind, sub in (('small', '011'), ('micro', '012')):
            report = self._year('l10n_ua.small.report', kind=kind)
            root = self._xml(report)
            self.assertEqual(root.find('DECLARHEAD').findtext('C_DOC_SUB'), sub)
            body = root.find('DECLARBODY')
            self.assertEqual(body.findtext('HPERIOD'), '31 грудня')
            self.assertEqual(body.findtext('HPERIOD1'), 'рік')
            self.assertEqual(body.findtext('R1300G4'), '354.0')

    # ------------------------------------------------------------ перевірки

    def test_draft_refused(self):
        report = self.env['l10n_ua.balance.report'].create(
            {'company_id': self.company.id, 'date_to': date(Y, 12, 31)})
        report.action_compute()
        with self.assertRaisesRegex(UserError, 'затвердіть'):
            report.action_generate_dps_xml()

    def test_period_must_end_a_quarter_from_january(self):
        report = self._confirmed('l10n_ua.balance.report', date_to=date(Y, 5, 31))
        with self.assertRaisesRegex(UserError, 'кварталу'):
            report.action_generate_dps_xml()
        report = self._confirmed('l10n_ua.pnl.report', date_from=date(Y, 4, 1),
                                 date_to=date(Y, 6, 30))
        with self.assertRaisesRegex(UserError, 'кварталу'):
            report.action_generate_dps_xml()

    def test_requisites_listed(self):
        self.company.koatuu = False
        self.company.partner_id.l10n_ua_chief_name = False
        report = self._confirmed('l10n_ua.balance.report', date_to=date(Y, 12, 31))
        if 'director_id' in self.company._fields:
            self.company.director_id = False
        with self.assertRaisesRegex(UserError, '(?s)КОАТУУ.*керівника'):
            report.action_generate_dps_xml()

    # --------------------------------------------------------------- подання

    def test_submit(self):
        report = self._confirmed('l10n_ua.pnl.report', date_from=date(Y, 1, 1),
                                 date_to=date(Y, 12, 31))
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = report.kep_prepare_signing()
        self.assertEqual(spec['documents'][0]['filename'], report.xml_filename)
        with patch(CONFIG + '._api_submit_document_presigned',
                   return_value=[{'status': 'OK', 'message': 'Прийнято'}]):
            report.kep_submit_signed({'doc': 'SIGNED'}, 'AUTH')
        self.assertTrue(report.submission_date)
        with self.assertRaisesRegex(UserError, 'подано'):
            report.action_draft()
