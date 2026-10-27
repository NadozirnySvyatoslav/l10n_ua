"""XML декларації з ПДВ (J0200126), Д1 (J0200526) і Д2 (J0215226): рядки, XSD, подання.

XSD у `tests/schemas` — контрольні схеми з пакета СКЗ ДПС (повна версія
1.34.0.0, tax.gov.ua/data/files/627351.zip), форма за наказом № 400.
"""

import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')
CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'


def _schema(name):
    return etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, name)))


@tagged('post_install', '-at_install')
class TestVatDeclarationXml(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        office = cls.env['l10n_ua.tax.office'].search([('code', '=', '2650')], limit=1) or \
            cls.env['l10n_ua.tax.office'].create({'name': 'ГУ ДПС у м. Києві', 'code': '2650'})
        cls.company.write({
            'l10n_ua_is_vat_payer': True,
            'edrpou': '12345678',
            'l10n_ua_vat_ipn': '123456789012',
            'l10n_ua_tax_office_id': office.id,
            'city': 'Київ', 'street': 'вул. Хрещатик, 1', 'zip': '01001',
        })
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'ТОВ Постачальник', 'ipn': '987654321098'})
        cls.supplier2 = cls.env['res.partner'].create(
            {'name': 'ТОВ Другий постачальник', 'ipn': '111111111111'})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'ТОВ Покупець', 'ipn': '222222222222'})
        cls.period = cls.env['l10n_ua.tax.period'].create({
            'name': 'Вересень 2026', 'date_start': date(2026, 9, 1),
            'date_end': date(2026, 9, 30), 'period_type': 'month', 'month': 9,
            'year': 2026, 'quarter': 3, 'company_id': cls.company.id,
        })
        Register = cls.env['l10n_ua.vat.register']
        cls.issued = Register.create({'register_type': 'issued', 'period_id': cls.period.id,
                                      'company_id': cls.company.id})
        cls.received = Register.create({'register_type': 'received', 'period_id': cls.period.id,
                                        'company_id': cls.company.id})
        Line = cls.env['l10n_ua.vat.register.line']
        Line.create({'register_id': cls.issued.id, 'date': date(2026, 9, 10),
                     'partner_id': cls.customer.id, 'base_amount': 100000.40,
                     'vat_amount': 20000.08, 'base_20': 100000.40, 'vat_20': 20000.08})
        for partner, day, base, vat in ((cls.supplier, 5, 30000.0, 6000.0),
                                        (cls.supplier, 20, 10000.25, 2000.05),
                                        (cls.supplier2, 12, 5000.0, 1000.0)):
            Line.create({'register_id': cls.received.id, 'date': date(2026, 9, day),
                         'partner_id': partner.id, 'base_amount': base, 'vat_amount': vat,
                         'base_20': base, 'vat_20': vat})
        Line.create({'register_id': cls.received.id, 'date': date(2026, 9, 25),
                     'doc_type': 'rk', 'partner_id': cls.supplier.id, 'base_amount': -1000.0,
                     'vat_amount': -200.0, 'base_20': -1000.0, 'vat_20': -200.0})

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def test_rows_follow_form_400(self):
        decl = self._declaration()
        self.assertEqual(decl.line_1_1_vat, 20000)       # цілі гривні
        self.assertEqual(decl.line_10_1_vat, 9000)        # 6000 + 2000.05 + 1000
        self.assertEqual(decl.line_14_vat, -200)          # отримані РК
        self.assertEqual(decl.line_17_vat, 8800)
        self.assertEqual(decl.line_18_vat, 11200)
        self.assertEqual(decl.line_19_vat, 0)

    def test_xml_is_valid_against_dps_xsd(self):
        decl = self._declaration()
        decl.action_generate_xml()
        main = base64.b64decode(decl.xml_file)
        d1 = base64.b64decode(decl.d1_xml_file)
        _schema('J0200126.xsd').assertValid(etree.fromstring(main))
        _schema('J0200526.xsd').assertValid(etree.fromstring(d1))
        # Ім'я файлу — за наказом № 729; декларація й Д1 посилаються одна на одну.
        # C_REG C_RAJ TIN C_DOC SUB VER STAN TYPE CNT PERIOD_TYPE MONTH YEAR C_STI_ORIG
        self.assertEqual(decl.xml_filename, '26500012345678J0200126100000000110920262650.xml')
        self.assertEqual(decl.d1_xml_filename, '26500012345678J0200526100000000110920262650.xml')
        self.assertIn(decl.d1_xml_filename[:-4].encode() + b'.XML', main)
        self.assertIn(decl.xml_filename[:-4].encode() + b'.XML', d1)
        root = etree.fromstring(main)
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('R11GB'), '20000')
        self.assertEqual(body.findtext('R101GB'), '9000')
        self.assertEqual(body.findtext('R140GB'), '-200')
        self.assertEqual(body.findtext('R180GB'), '11200')
        self.assertEqual(body.findtext('HD1'), '1')

    def test_d1_groups_suppliers_by_period(self):
        decl = self._declaration()
        decl.action_generate_xml()
        body = etree.fromstring(base64.b64decode(decl.d1_xml_file)).find('DECLARBODY')
        ipns = [el.text for el in body.findall('T21RXXXXG2')]
        self.assertEqual(sorted(ipns), ['111111111111', '987654321098'])
        supplier_row = ipns.index('987654321098') + 1
        vat = body.find(f'T21RXXXXG7[@ROWNUM="{supplier_row}"]').text
        self.assertEqual(vat, '8000.05')
        self.assertEqual(body.findtext('R021G10'), '9000')
        self.assertEqual(body.findtext('T22RXXXXG2'), '987654321098')
        self.assertEqual(body.findtext('T22RXXXXG8'), '-200.00')

    def test_missing_requisites_are_reported_together(self):
        decl = self._declaration()
        decl.signatory_rnokpp = False
        self.supplier2.ipn = False
        with self.assertRaises(UserError) as err:
            decl.action_generate_xml()
        self.assertIn('РНОКПП', str(err.exception))
        self.assertIn('ТОВ Другий постачальник', str(err.exception))

    def _add_received(self, partner, day, vat, month=9):
        self.env['l10n_ua.vat.register.line'].create({
            'register_id': self.received.id, 'date': date(2026, month, day),
            'partner_id': partner.id, 'base_amount': vat * 5, 'vat_amount': vat,
            'base_20': vat * 5, 'vat_20': vat})

    def _prev_declaration(self, line_21, d2_rows=()):
        prev_period = self.env['l10n_ua.tax.period'].create({
            'name': 'Серпень 2026', 'date_start': date(2026, 8, 1),
            'date_end': date(2026, 8, 31), 'period_type': 'month', 'month': 8,
            'year': 2026, 'quarter': 3, 'company_id': self.company.id,
        })
        prev = self.env['l10n_ua.vat.declaration'].create(
            {'period_id': prev_period.id, 'company_id': self.company.id})
        prev.write({'line_10_1_vat': line_21, 'state': 'calculated',
                    'vat_limit_amount': 10 ** 9,
                    'd2_line_ids': [(0, 0, row) for row in d2_rows]})
        self.assertEqual(prev.line_21_vat, line_21)
        return prev

    def test_negative_value_goes_to_d2_latest_purchases_first(self):
        supplier3 = self.env['res.partner'].create({'name': 'ТОВ Третій', 'ipn': '333333333333'})
        self._add_received(supplier3, 3, 25000.0)
        decl = self._declaration()
        decl.vat_limit_amount = 10000
        # 10.1 = 6000 + 2000.05 + 1000 + 25000 → 34000; 17 = 33800; 19 = 33800 − 20000.
        self.assertEqual(decl.line_19_vat, 13800)
        self.assertEqual((decl.line_19_1_vat, decl.line_20_vat, decl.line_20_3_vat),
                         (3800, 10000, 10000))
        self.assertEqual(decl.line_21_vat, 13800)
        # Нова частина — на найпізніші ПН: Постачальник (20.09), Другий (12.09), Третій (03.09).
        by_ipn = {l.partner_ipn: l.amount for l in decl.d2_line_ids}
        self.assertEqual(by_ipn, {'987654321098': 8000.05, '111111111111': 1000.0,
                                  '333333333333': 4799.95})
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        d2 = etree.fromstring(base64.b64decode(decl.d2_xml_file))
        _schema('J0200126.xsd').assertValid(main)
        _schema('J0215226.xsd').assertValid(d2)
        body = main.find('DECLARBODY')
        self.assertEqual([body.findtext(t) for t in
                          ('R190GB', 'R191G3', 'R191GB', 'R200GB', 'R203GB', 'R210GB', 'HD2')],
                         ['13800', '10000', '3800', '10000', '10000', '13800', '1'])
        self.assertEqual(decl.d2_xml_filename, '26500012345678J0215226100000000110920262650.xml')
        self.assertEqual(len(main.findall('DECLARHEAD/LINKED_DOCS/DOC')), 2)
        self.assertIn(decl.xml_filename[:-4].encode() + b'.XML', base64.b64decode(decl.d2_xml_file))
        d2body = d2.find('DECLARBODY')
        self.assertEqual(d2body.findtext('R01G6'), '13800')
        self.assertEqual(d2body.findtext('R01G10'), '13800')
        self.assertEqual(d2body.findtext('R02G3'), '10000')
        self.assertEqual(sorted(e.text for e in d2body.findall('T1RXXXXG6')),
                         ['1000.00', '4799.95', '8000.05'])

    def test_d2_keeps_previous_rows_and_repays_oldest_first(self):
        self._prev_declaration(3000, [
            {'origin_month': 7, 'origin_year': 2026, 'partner_ipn': '987654321098',
             'doc_month': 7, 'doc_year': 2026, 'amount': 1000},
            {'origin_month': 8, 'origin_year': 2026, 'partner_ipn': '111111111111',
             'doc_month': 8, 'doc_year': 2026, 'amount': 2000},
        ])
        supplier3 = self.env['res.partner'].create({'name': 'ТОВ Третій', 'ipn': '333333333333'})
        self._add_received(supplier3, 3, 10000.0)
        decl = self._declaration()
        # 17 = 19000 − 200 + 3000 = 21800; 19 = 1800 < 16.1 — гаситься найстаріше (липень).
        self.assertEqual(decl.line_19_vat, 1800)
        rows = [(l.origin_month, l.partner_ipn, l.amount) for l in decl.d2_line_ids]
        self.assertEqual(rows, [(8, '111111111111', 1800.0)])
        decl.vat_limit_amount = 50000
        decl.action_generate_xml()
        _schema('J0215226.xsd').assertValid(etree.fromstring(base64.b64decode(decl.d2_xml_file)))

    def test_d2_without_previous_rows_uses_own_ipn(self):
        self._prev_declaration(3000)
        supplier3 = self.env['res.partner'].create({'name': 'ТОВ Третій', 'ipn': '333333333333'})
        self._add_received(supplier3, 3, 15000.0)
        decl = self._declaration()
        # 17 = 24000 − 200 + 3000 = 26800; 19 = 6800: 3000 з серпня + 3800 нових.
        self.assertEqual(decl.line_19_vat, 6800)
        rows = [(l.origin_month, l.partner_ipn, l.amount) for l in decl.d2_line_ids]
        self.assertEqual(rows, [(8, '123456789012', 3000.0), (9, '987654321098', 3800.0)])

    def test_d2_totals_must_match_rows(self):
        self._add_received(self.supplier2, 3, 25000.0)
        decl = self._declaration()
        decl.d2_line_ids[:1].amount += 100
        with self.assertRaisesRegex(UserError, 'графи 6'):
            decl.action_generate_xml()

    def test_unregistered_issued_go_to_d1_section_1(self):
        Invoice = self.env['l10n_ua.tax.invoice']
        Line = self.env['l10n_ua.vat.register.line']
        common = {'invoice_type': 'issued', 'company_id': self.company.id,
                  'partner_id': self.customer.id}
        pn = Invoice.create({**common, 'doc_type': 'pn', 'number': '41',
                             'date': date(2026, 9, 29)})
        rk = Invoice.create({**common, 'doc_type': 'rk', 'number': '42',
                             'date': date(2026, 9, 30)})
        for inv, base, vat in ((pn, 5000.0, 1000.0), (rk, 500.0, 100.0)):
            Line.create({'register_id': self.issued.id, 'date': inv.date,
                         'doc_type': inv.doc_type, 'tax_invoice_id': inv.id,
                         'partner_id': self.customer.id, 'invoice_number': inv.number,
                         'invoice_date': inv.date, 'base_amount': base, 'vat_amount': vat,
                         'base_20': base, 'vat_20': vat})
        decl = self._declaration()
        decl.action_generate_xml()
        d1 = etree.fromstring(base64.b64decode(decl.d1_xml_file))
        _schema('J0200526.xsd').assertValid(d1)
        body = d1.find('DECLARBODY')
        self.assertEqual(body.findtext('T111RXXXXG2'), '222222222222')
        self.assertEqual(body.findtext('T111RXXXXG3D'), '29092026')
        self.assertEqual(body.findtext('T111RXXXXG4S'), '41')
        self.assertEqual(body.findtext('T111RXXXXG7'), '1000.00')
        self.assertEqual(body.findtext('R0111G7'), '1000')
        self.assertEqual(body.findtext('T121RXXXXG4S'), '42')
        self.assertEqual(body.findtext('R0121G6'), '500')
        self.assertIsNone(body.find('T112RXXXXG2'))
        # Таблиці 2.1/2.2 лишаються в тому самому файлі.
        self.assertIsNotNone(body.find('T21RXXXXG2'))

    def test_unregistered_decreasing_rk_is_refused(self):
        rk = self.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'issued', 'company_id': self.company.id,
            'partner_id': self.customer.id, 'doc_type': 'rk', 'number': '43',
            'date': date(2026, 9, 30)})
        self.env['l10n_ua.vat.register.line'].create({
            'register_id': self.issued.id, 'date': rk.date, 'doc_type': 'rk',
            'tax_invoice_id': rk.id, 'partner_id': self.customer.id,
            'base_amount': -500.0, 'vat_amount': -100.0, 'base_20': -500.0, 'vat_20': -100.0})
        decl = self._declaration()
        with self.assertRaisesRegex(UserError, 'РК на зменшення'):
            decl.action_generate_xml()

    def test_previous_negative_value_goes_to_16_1(self):
        prev_period = self.env['l10n_ua.tax.period'].create({
            'name': 'Серпень 2026', 'date_start': date(2026, 8, 1),
            'date_end': date(2026, 8, 31), 'period_type': 'month', 'month': 8,
            'year': 2026, 'quarter': 3, 'company_id': self.company.id,
        })
        prev = self.env['l10n_ua.vat.declaration'].create(
            {'period_id': prev_period.id, 'company_id': self.company.id})
        prev.write({'line_10_1_vat': 3000, 'state': 'calculated'})
        self.assertEqual(prev.line_21_vat, 3000)
        decl = self._declaration()
        self.assertEqual(decl.line_16_1_vat, 3000)
        self.assertEqual(decl.line_18_vat, 11200 - 3000)

    def test_submit_sends_declaration_and_d1_together(self):
        decl = self._declaration()
        decl.action_generate_xml()
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = decl.kep_prepare_signing()
        self.assertEqual([d['name'] for d in spec['documents']], ['doc', 'd1'])
        self.assertEqual(spec['documents'][1]['filename'], decl.d1_xml_filename)

        posted = {}

        def fake_post(config, content, fname, headers, extra_files=()):
            posted['files'] = [fname] + [f for _c, f in extra_files]
            return [{'status': 'OK', 'id': 1}, {'status': 'OK', 'id': 2}]

        with patch(CONFIG + '._post_report', autospec=True, side_effect=fake_post):
            decl.kep_submit_signed({'doc': 'ENV1', 'd1': 'ENV2'}, 'AUTH')
        self.assertEqual(posted['files'], [decl.xml_filename, decl.d1_xml_filename])
        self.assertEqual(decl.state, 'submitted')

    def test_submit_sends_declaration_d1_and_d2_together(self):
        self._add_received(self.supplier2, 3, 25000.0)
        decl = self._declaration()
        decl.action_generate_xml()
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = decl.kep_prepare_signing()
        self.assertEqual([d['name'] for d in spec['documents']], ['doc', 'd1', 'd2'])
        posted = {}

        def fake_post(config, content, fname, headers, extra_files=()):
            posted['files'] = [fname] + [f for _c, f in extra_files]
            return [{'status': 'OK', 'id': n} for n in (1, 2, 3)]

        with patch(CONFIG + '._post_report', autospec=True, side_effect=fake_post):
            with self.assertRaisesRegex(UserError, 'D2'):
                decl.kep_submit_signed({'doc': 'ENV1', 'd1': 'ENV2'}, 'AUTH')
            decl.kep_submit_signed({'doc': 'ENV1', 'd1': 'ENV2', 'd2': 'ENV3'}, 'AUTH')
        self.assertEqual(posted['files'],
                         [decl.xml_filename, decl.d1_xml_filename, decl.d2_xml_filename])
        self.assertEqual(decl.state, 'submitted')
