"""Декларація з податку на прибуток (J0100129 + РІ J0111829): розрахунок, XSD, подання.

Кожен XML перевіряється офіційною XSD уже під час формування (``_render``), тож
«сформувалось» — це й тест валідності; тут додатково перевіряємо його вміст.
Дати — 2046 рік, як у тестах l10n_ua_accounting.
"""
import base64
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools.misc import file_path

from odoo.addons.l10n_ua_accounting.tests.common import AccountingTestCase

CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'
Y = 2046


@tagged('post_install', '-at_install', 'l10n_ua_profit_tax')
class TestProfitTaxDeclaration(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Office = cls.env['l10n_ua.tax.office'].sudo()
        office = Office.search([('code', '=', '2650')], limit=1) or \
            Office.create({'code': '2650', 'name': 'ГУ ДПС у м. Києві'})
        cls.company.write({
            'name': 'ТОВ «Прибуток»',
            'edrpou': '12345678', 'tax_office_code': '2650',
            'l10n_ua_tax_office_id': office.id,
            'kved_main': '62.01', 'zip': '01001', 'city': 'Київ',
            'street': 'вул. Хрещатик, 1', 'phone': '044 123-45-67',
        })
        if 'director_id' in cls.company._fields:
            cls.company.director_id = False
        if 'accountant_id' in cls.company._fields:
            cls.company.accountant_id = False
        cls.company.partner_id.write({
            'l10n_ua_chief_name': 'Іван ПЕТРЕНКО',
            'l10n_ua_accountant_name': 'Ольга КОВАЛЬ',
        })
        acc = cls._account
        cls.acc_311 = acc('311', 'Рахунок у банку', 'asset_cash')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_719 = acc('719', 'Інші доходи від операційної діяльності', 'income')
        cls.acc_733 = acc('733', 'Інші доходи від фінансових операцій', 'income')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')
        # I квартал: дохід 1 000 000 + 20 000 + 5 000, витрати 425 000,4 → прибуток 600 000.
        cls._entry(cls.acc_361, cls.acc_702, 1000000.0, date(Y, 2, 10))
        cls._entry(cls.acc_311, cls.acc_719, 20000.0, date(Y, 2, 15))
        cls._entry(cls.acc_311, cls.acc_733, 5000.0, date(Y, 3, 1))
        cls._entry(cls.acc_92, cls.acc_311, 425000.4, date(Y, 3, 20))
        # II квартал: ще 300 000 доходу.
        cls._entry(cls.acc_361, cls.acc_702, 300000.0, date(Y, 5, 10))

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

    def _declaration(self, period, **vals):
        decl = self.env['l10n_ua.profit.tax.declaration'].create({
            'company_id': self.company.id, 'year': Y, 'period': period,
            'signatory_rnokpp': '1234567890', **vals,
        })
        decl.action_calculate()
        return decl

    @staticmethod
    def _parse(data):
        return etree.fromstring(base64.b64decode(data))

    def _submit(self, decl):
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = decl.kep_prepare_signing()
        signed = {doc['name']: 'SIGNED' for doc in spec['documents']}
        with patch(CONFIG + '._api_submit_document_presigned',
                   return_value=[{'status': 'OK', 'message': 'Прийнято', 'id': 77}]) as api:
            decl.kep_submit_signed(signed, 'AUTH')
        return spec, api

    # ------------------------------------------------------------ розрахунок

    def test_calculation_from_accounting(self):
        decl = self._declaration('q1')
        # 01 — 2000 + 2120 + 2220 (70, 71, 73), у гривнях, не в тисячах.
        self.assertEqual(decl.line_01, 1025000)
        self.assertEqual(decl.line_02, 600000)
        self.assertEqual(decl.line_04, 600000)
        self.assertEqual(decl.line_06, 108000)
        self.assertEqual(decl.line_17, 108000)
        self.assertEqual(decl.line_19, 108000)
        self.assertEqual(decl.state, 'calculated')

    def test_tax_differences(self):
        decl = self._declaration('q1', ri_2_1_1=10000.0, ri_3_1_11=1500.0,
                                 ri_2_2_1=4000.0, ri_3_2_4=7500.0)
        self.assertEqual(decl.ri_increase, 11500)
        self.assertEqual(decl.ri_decrease, 11500)
        self.assertEqual(decl.line_03, 0)
        decl.ri_3_2_4 = 107500.0
        self.assertEqual(decl.line_03, -100000)
        self.assertEqual(decl.line_04, 500000)
        self.assertEqual(decl.line_06, 90000)

    def test_loss_gives_no_tax(self):
        decl = self._declaration('q1', ri_3_2_4=700000.0)
        self.assertEqual(decl.line_04, -100000)
        self.assertEqual(decl.line_06, 0)

    # ------------------------------------------------------------------- XML

    def test_xml_without_appendix(self):
        decl = self._declaration('q1')
        decl.action_generate_xml()
        self.assertFalse(decl.ri_xml_file)
        root = self._parse(decl.xml_file)
        head, body = root.find('DECLARHEAD'), root.find('DECLARBODY')
        self.assertEqual(head.findtext('C_DOC') + head.findtext('C_DOC_SUB')
                         + head.findtext('C_DOC_VER'), 'J0100129')
        self.assertEqual((head.findtext('PERIOD_TYPE'), head.findtext('PERIOD_MONTH')), ('2', '3'))
        self.assertEqual((head.findtext('C_DOC_STAN'), head.findtext('C_DOC_TYPE')), ('1', '0'))
        self.assertIsNone(head.find('LINKED_DOCS/DOC'))
        for tag, value in (('HZ', '1'), ('H1KV', '1'), ('H01', '1'), ('HZY', str(Y)),
                           ('HTIN', '12345678'), ('HKVED', '62.01'), ('HSTI', 'ГУ ДПС у м. Києві'),
                           ('R001G3', '1025000'), ('R002G3', '600000'), ('R004G3', '600000'),
                           ('R006G1', '18.00'), ('R006G3', '108000'), ('R017G3', '108000'),
                           ('R019G3', '108000'), ('HBOS', 'Іван ПЕТРЕНКО'),
                           ('HKBOS', '1234567890'), ('HBUH', 'Ольга КОВАЛЬ')):
            self.assertEqual(body.findtext(tag), value, tag)
        for tag in ('R003G3', 'HD6', 'R018G3', 'HJ2', 'HKBUH'):
            self.assertIsNone(body.find(tag), tag)
        self.assertIn('J0100129', decl.xml_filename)
        self.assertTrue(decl.xml_filename.startswith('2650'))

    def test_xml_with_appendix_ri(self):
        decl = self._declaration('q1', ri_2_1_2=3000.0, ri_2_2_3=1000.0)
        decl.action_generate_xml()
        main, ri = self._parse(decl.xml_file), self._parse(decl.ri_xml_file)
        body = main.find('DECLARBODY')
        self.assertEqual(body.findtext('R003G3'), '2000')
        self.assertEqual(body.findtext('R004G3'), '602000')
        self.assertEqual(body.findtext('HD6'), '1')
        ri_head, ri_body = ri.find('DECLARHEAD'), ri.find('DECLARBODY')
        self.assertEqual(ri_head.findtext('C_DOC_SUB'), '118')
        self.assertEqual(ri_body.findtext('R0212G3'), '3000')
        self.assertEqual(ri_body.findtext('R0223G3'), '1000')
        self.assertEqual(ri_body.findtext('R001G3'), '3000')
        self.assertEqual(ri_body.findtext('R002G3'), '1000')
        self.assertEqual(ri_body.findtext('R003G3'), '2000')
        # Посилання в обидва боки: декларація → додаток (TYPE 1), додаток → декларація (2).
        link = main.find('DECLARHEAD/LINKED_DOCS/DOC')
        self.assertEqual((link.get('TYPE'), link.findtext('C_DOC_SUB')), ('1', '118'))
        self.assertEqual(link.findtext('FILENAME')[:-4], decl.ri_xml_filename[:-4])
        back = ri.find('DECLARHEAD/LINKED_DOCS/DOC')
        self.assertEqual((back.get('TYPE'), back.findtext('C_DOC_SUB')), ('2', '001'))
        self.assertEqual(back.findtext('FILENAME')[:-4], decl.xml_filename[:-4])

    def test_annual_small_payer_without_adjustments(self):
        decl = self._declaration('year', base_period='year', no_adjustments=True,
                                 ri_3_2_4=100000.0)
        decl.action_generate_xml()
        body = self._parse(decl.xml_file).find('DECLARBODY')
        self.assertEqual(self._parse(decl.xml_file).findtext('DECLARHEAD/PERIOD_TYPE'), '5')
        for tag, value in (('HY', '1'), ('H02', '1'), ('HJ2', '1'), ('HD6', '1'),
                           ('R001G3', '1325000'), ('R002G3', '900000'), ('R003G3', '-100000'),
                           ('R004G3', '800000'), ('R006G3', '144000'), ('R019G3', '144000')):
            self.assertEqual(body.findtext(tag), value, tag)
        self.assertIsNone(body.find('H01'))
        self.assertIsNone(body.find('R018G3'))
        ri_body = self._parse(decl.ri_xml_file).find('DECLARBODY')
        self.assertEqual(ri_body.findtext('R0324G3'), '100000')
        self.assertEqual(ri_body.findtext('HY'), '1')

    def test_xsd_files_are_the_official_ones(self):
        """XSD у модулі — без змін із СКЗ: фіксована версія 29 і кодування cp1251."""
        for form, sub in (('J0100129', '001'), ('J0111829', '118')):
            with open(file_path('l10n_ua_profit_tax/data/xsd/%s.xsd' % form), 'rb') as f:
                tree = etree.parse(f)
            fixed = {el.get('name'): el.get('fixed') for el in tree.iter(
                '{http://www.w3.org/2001/XMLSchema}element') if el.get('fixed')}
            self.assertEqual((fixed['C_DOC_SUB'], fixed['C_DOC_VER']), (sub, '29'))
            self.assertEqual(tree.docinfo.encoding.lower(), 'windows-1251')

    # --------------------------------------------------------------- подання

    def test_quarterly_previous_period_and_submit(self):
        q1 = self._declaration('q1', ri_2_1_1=10000.0)
        spec, api = self._submit(q1)
        self.assertEqual([d['name'] for d in spec['documents']], ['doc', 'ri'])
        self.assertEqual(api.call_args.kwargs['extra_files'], [('SIGNED', q1.ri_xml_filename)])
        self.assertEqual(q1.state, 'submitted')
        self.assertEqual(q1.dps_submission_id, '77')
        self.assertEqual(q1.line_17, 109800)
        with self.assertRaisesRegex(UserError, 'подано'):
            q1.ri_2_1_1 = 0.0

        h1 = self._declaration('h1')
        # Рядок 18 — рядок 17 поданої декларації за I квартал.
        self.assertEqual(h1.line_18, 109800)
        self.assertEqual(h1.line_17, 162000)
        self.assertEqual(h1.line_19, 52200)
        h1.action_generate_xml()
        body = self._parse(h1.xml_file).find('DECLARBODY')
        self.assertEqual(body.findtext('HHY'), '1')
        self.assertEqual(body.findtext('R018G3'), '109800')
        self.assertEqual(body.findtext('R019G3'), '52200')
        spec, api = self._submit(h1)
        self.assertEqual(len(spec['documents']), 1)
        self.assertFalse(api.call_args.kwargs.get('extra_files'))
        self.assertEqual(h1.state, 'submitted')

    def test_new_reporting_declaration(self):
        q1 = self._declaration('q1')
        self._submit(q1)
        with self.assertRaises(ValidationError):
            self._declaration('q1')
        new = self._declaration('q1', doc_kind='HZN')
        new.action_generate_xml()
        root = self._parse(new.xml_file)
        self.assertEqual((root.findtext('DECLARHEAD/C_DOC_STAN'),
                          root.findtext('DECLARHEAD/C_DOC_TYPE')), ('2', '1'))
        self.assertEqual(root.findtext('DECLARBODY/HZN'), '1')
        self.assertIsNone(root.find('DECLARBODY/HZ'))

    # ------------------------------------------------------------ перевірки

    def test_annual_base_only_for_year(self):
        with self.assertRaises(ValidationError):
            self._declaration('h1', base_period='year')

    def test_no_adjustments_keeps_only_losses(self):
        with self.assertRaisesRegex(ValidationError, '2.1.1'):
            self._declaration('year', no_adjustments=True, ri_2_1_1=1000.0)

    def test_old_period_not_supported(self):
        decl = self.env['l10n_ua.profit.tax.declaration'].create(
            {'company_id': self.company.id, 'year': 2025, 'period': '9m'})
        with self.assertRaisesRegex(UserError, 'версії форми'):
            decl.action_calculate()

    def test_requisites_listed(self):
        decl = self._declaration('q1', signatory_rnokpp=False)
        self.company.kved_main = False
        if self.company.l10n_ua_kved_ids:
            self.company.l10n_ua_kved_ids.unlink()
        with self.assertRaisesRegex(UserError, '(?s)КВЕД.*РНОКПП'):
            decl.action_generate_xml()

    def test_draft_refused(self):
        decl = self.env['l10n_ua.profit.tax.declaration'].create(
            {'company_id': self.company.id, 'year': Y, 'period': 'q1',
             'signatory_rnokpp': '1234567890'})
        with self.assertRaisesRegex(UserError, 'розрахуйте'):
            decl.action_generate_xml()
