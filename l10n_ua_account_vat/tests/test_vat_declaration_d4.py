"""Додаток 4 (J0299326 / F0299326): пільги, рядки 5/5.1, XSD."""

import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')


def _schema(name):
    return etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, name)))


@tagged('post_install', '-at_install')
class TestVatDeclarationD4(TransactionCase):

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
        cls.Line = cls.env['l10n_ua.vat.register.line']
        cls.Line.create({'register_id': cls.issued.id, 'date': date(2026, 9, 10),
                         'partner_id': cls.customer.id, 'base_amount': 10000.0,
                         'vat_amount': 2000.0, 'base_20': 10000.0, 'vat_20': 2000.0})
        # ПН зі звільненими рядками за двома кодами пільг (+ рядок 20 %).
        inv1 = cls._invoice('101', [('Ліки', 3000.0, 'exempt', '14060509'),
                                    ('Освіта', 2000.0, 'exempt', '14060531'),
                                    ('Товар', 1000.0, '20', False)])
        inv2 = cls._invoice('102', [('Ліки', 1500.0, 'exempt', '14060509')])
        for inv, exempt in ((inv1, 5000.0), (inv2, 1500.0)):
            cls.Line.create({'register_id': cls.issued.id, 'date': date(2026, 9, 15),
                             'partner_id': cls.customer.id, 'tax_invoice_id': inv.id,
                             'base_amount': exempt, 'base_exempt': exempt})

    @classmethod
    def _invoice(cls, number, lines):
        return cls.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'issued', 'doc_type': 'pn', 'number': number,
            'date': date(2026, 9, 15), 'partner_id': cls.customer.id,
            'company_id': cls.company.id,
            'line_ids': [(0, 0, {'name': name, 'quantity': 1.0, 'price_unit': price,
                                 'vat_rate': rate, 'benefit_code': code})
                         for name, price, rate, code in lines],
        })

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def _t2(self, decl, code):
        return decl.d4_t2_line_ids.filtered(lambda l: l.benefit_code == code)

    def test_table2_grouped_by_benefit_code(self):
        decl = self._declaration()
        self.assertEqual(decl.line_5_base, 6500)
        self.assertEqual(decl.line_5_1_base, 6500)
        self.assertEqual(len(decl.d4_t2_line_ids), 2)
        self.assertEqual(self._t2(decl, '14060509').supply_amount, 4500.0)
        self.assertEqual(self._t2(decl, '14060531').supply_amount, 2000.0)
        self.assertEqual(self._t2(decl, '14060509').vat_unpaid, 900.0)

    def test_xml_valid_and_flagged_in_main(self):
        decl = self._declaration()
        decl.action_generate_xml()
        self.assertTrue(decl.d4_xml_file)
        d4 = etree.fromstring(base64.b64decode(decl.d4_xml_file))
        _schema('J0299326.xsd').assertValid(d4)
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        _schema('J0200126.xsd').assertValid(main)
        body = main.find('DECLARBODY')
        self.assertEqual(body.findtext('HD4'), '1')
        self.assertEqual(body.findtext('R50GA'), '6500')
        self.assertEqual(body.findtext('R51GA'), '6500')
        d4_body = d4.find('DECLARBODY')
        self.assertEqual([e.text for e in d4_body.findall('T2RXXXXG3')],
                         ['14060509', '14060531'])
        self.assertEqual(d4_body.findtext('R02G5'), '6500')
        self.assertEqual(d4_body.findtext('R02G4'), '1300')
        self.assertIsNone(d4_body.find('R01G4'))
        self.assertIn(decl.d4_xml_filename[:-4].encode() + b'.XML',
                      base64.b64decode(decl.xml_file))

    def test_table1_increases_row5_only(self):
        decl = self._declaration()
        decl.write({'d4_t1_line_ids': [
            (0, 0, {'operation_type': 'non_object', 'name': 'Компенсація',
                    'article': '196.1.1', 'amount': 700.40}),
            (0, 0, {'operation_type': 'abroad', 'name': 'Консультації нерезиденту',
                    'article': '186.3', 'amount': 300.0}),
        ]})
        with self.assertRaises(UserError):
            decl.action_generate_xml()        # рядок 5 ще не перераховано
        decl.action_calculate()
        self.assertEqual(decl.line_5_base, 7500)
        self.assertEqual(decl.line_5_1_base, 6500)
        decl.action_calculate()               # повторний розрахунок не подвоює
        self.assertEqual(decl.line_5_base, 7500)
        decl.action_generate_xml()
        d4 = etree.fromstring(base64.b64decode(decl.d4_xml_file))
        _schema('J0299326.xsd').assertValid(d4)
        body = d4.find('DECLARBODY')
        self.assertEqual(body.findtext('T11RXXXXG3S'), '196.1.1')
        self.assertEqual(body.findtext('R011G4'), '700.40')
        self.assertEqual(body.findtext('R012G4'), '300.00')
        self.assertEqual(body.findtext('R01G4'), '1000')

    def test_g4_formula_and_negative_not_filled(self):
        decl = self._declaration()
        line = self._t2(decl, '14060509')
        # 4500 × 20 % − 1000 × 20 % − 2000 × 7 % − 500 × 14 % (0 % не впливає) = 490
        line.write({'purchase_20': 1000.0, 'purchase_7': 2000.0, 'purchase_0': 9999.0,
                    'purchase_14': 500.0})
        self.assertAlmostEqual(line.vat_unpaid, 490.0)
        other = self._t2(decl, '14060531')
        other.purchase_20 = 5000.0           # 2000 × 20 % − 5000 × 20 % < 0
        self.assertEqual(other.vat_unpaid, 0.0)
        # Ручні графи 6–9 переживають перерахунок.
        decl.action_calculate()
        self.assertEqual(self._t2(decl, '14060509').purchase_7, 2000.0)
        decl.action_generate_xml()
        d4 = etree.fromstring(base64.b64decode(decl.d4_xml_file))
        _schema('J0299326.xsd').assertValid(d4)
        body = d4.find('DECLARBODY')
        rows = [e.text for e in body.findall('T2RXXXXG3')]
        other_row = str(rows.index('14060531') + 1)
        self.assertIsNone(body.find(f'T2RXXXXG4[@ROWNUM="{other_row}"]'))
        self.assertEqual(body.findtext('R02G4'), '490')
        self.assertEqual(body.findtext('R02G8'), '9999')

    def test_missing_code_uses_conditional_code(self):
        inv = self._invoice('103', [('Без коду', 800.0, 'exempt', False)])
        self.Line.create({'register_id': self.issued.id, 'date': date(2026, 9, 20),
                          'partner_id': self.customer.id, 'tax_invoice_id': inv.id,
                          'base_amount': 800.0, 'base_exempt': 800.0})
        self.Line.create({'register_id': self.issued.id, 'date': date(2026, 9, 21),
                          'partner_id': self.customer.id, 'base_amount': 200.0,
                          'base_exempt': 200.0})     # без ПН
        decl = self._declaration()
        self.assertEqual(self._t2(decl, '99999999').supply_amount, 1000.0)
        self.assertEqual(decl.line_5_1_base, 7500)
        decl.action_generate_xml()
        _schema('J0299326.xsd').assertValid(
            etree.fromstring(base64.b64decode(decl.d4_xml_file)))

    def test_validation(self):
        decl = self._declaration()
        self._t2(decl, '14060531').write({'benefit_code': '123', 'supply_amount': 1.0})
        with self.assertRaises(UserError) as err:
            decl.action_generate_xml()
        self.assertIn('1406', str(err.exception))
        self.assertIn('рядку 5.1', str(err.exception))

    def test_tables_3_4_only(self):
        """Без рядка 5 Д4 подається для таблиць 3/4; без них — не подається."""
        self.issued.line_ids.filtered('base_exempt').unlink()
        decl = self._declaration()
        decl.action_generate_xml()
        self.assertFalse(decl.d4_xml_file)
        decl.write({'d4_disabled_staff_pct': 55.4, 'd4_disabled_payroll_pct': 26.0,
                    'd4_own_production_pct': 91.5, 'd4_capacity_mark': True})
        decl.action_generate_xml()
        body = etree.fromstring(base64.b64decode(decl.d4_xml_file)).find('DECLARBODY')
        self.assertEqual(body.findtext('R04G2'), '55')
        self.assertEqual(body.findtext('R05G2'), '26')
        self.assertIsNone(body.find('R06G2'))
        self.assertEqual(body.findtext('R07G2'), '92')
        self.assertEqual(body.findtext('R08G2'), '1')
        self.assertIsNone(body.find('R02G5'))

    def test_fop_declaration_uses_f_form(self):
        self.company.write({'vat': '3123456789'})
        with patch.object(type(self.env['l10n_ua.vat.declaration']), '_is_fop_declaration',
                          return_value=True):
            decl = self._declaration()
            decl.write({'d4_t1_line_ids': [(0, 0, {
                'operation_type': 'abroad', 'name': 'Послуги', 'article': '186.3',
                'amount': 100.0})], 'd4_processing_cost_pct': 12.0})
            decl.action_calculate()
            decl.action_generate_xml()
            d4 = etree.fromstring(base64.b64decode(decl.d4_xml_file))
            _schema('F0299326.xsd').assertValid(d4)
            _schema('F0200126.xsd').assertValid(
                etree.fromstring(base64.b64decode(decl.xml_file)))
        self.assertEqual(d4.findtext('DECLARHEAD/C_DOC'), 'F02')
