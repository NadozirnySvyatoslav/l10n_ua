"""Д6 (J0215826 / F0215826): заява із скаргою на контрагента — рядки, XSD, перевірки."""

import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')


def _schema(name):
    return etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, name)))


@tagged('post_install', '-at_install')
class TestVatDeclarationD6(TransactionCase):

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
            {'name': 'ТОВ "Постачальник" & Ко', 'ipn': '987654321098'})
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
        Register.create({'register_type': 'received', 'period_id': cls.period.id,
                         'company_id': cls.company.id})
        cls.env['l10n_ua.vat.register.line'].create({
            'register_id': cls.issued.id, 'date': date(2026, 9, 10),
            'partner_id': cls.customer.id, 'base_amount': 10000.0, 'vat_amount': 2000.0,
            'base_20': 10000.0, 'vat_20': 2000.0})

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def _complaints(self, decl):
        decl.write({
            'd6_attached_sheets': 3,
            'd6_line_ids': [
                (0, 0, {'doc_kind': 'pn', 'partner_id': self.supplier.id,
                        'partner_name': self.supplier.name, 'partner_ipn': '987654321098',
                        'doc_date': date(2026, 8, 14), 'doc_number': '125',
                        'base_amount': 50000.0, 'vat_amount': 10000.0,
                        'description': 'Продавець не зареєстрував ПН в ЄРПН\nу граничний строк'}),
                (0, 0, {'doc_kind': 'rk', 'partner_name': 'ТОВ Покупець',
                        'partner_ipn': '222222222222', 'doc_date': date(2026, 9, 2),
                        'base_amount': -1500.5, 'vat_amount': -300.1,
                        'description': 'Покупець не зареєстрував РК, номер невідомий'}),
            ],
        })

    def _generate(self, decl):
        decl.action_generate_xml()
        return (etree.fromstring(base64.b64decode(decl.xml_file)),
                etree.fromstring(base64.b64decode(decl.d6_xml_file)))

    def test_d6_xml_valid_and_linked(self):
        decl = self._declaration()
        self._complaints(decl)
        main, d6 = self._generate(decl)
        _schema('J0200126.xsd').assertValid(main)
        _schema('J0215826.xsd').assertValid(d6)
        self.assertEqual(decl.d6_xml_filename, '26500012345678J0215826100000000110920262650.xml')
        self.assertEqual(main.findtext('DECLARBODY/HD6'), '1')
        linked = [d.findtext('FILENAME') for d in main.findall('DECLARHEAD/LINKED_DOCS/DOC')]
        self.assertIn(decl.d6_xml_filename[:-4] + '.XML', linked)
        self.assertEqual(d6.findtext('DECLARHEAD/LINKED_DOCS/DOC/FILENAME'),
                         decl.xml_filename[:-4] + '.XML')
        body = d6.find('DECLARBODY')

        def col(tag):
            return {e.get('ROWNUM'): e.text for e in body.findall(tag)}

        self.assertEqual(col('T1RXXXXG2S'), {'1': 'Податкова накладна',
                                             '2': 'Розрахунок коригування'})
        self.assertEqual(col('T1RXXXXG3S'), {'1': 'ТОВ "Постачальник" & Ко',
                                             '2': 'ТОВ Покупець'})
        self.assertEqual(col('T1RXXXXG4'), {'1': '987654321098', '2': '222222222222'})
        self.assertEqual(col('T1RXXXXG5D'), {'1': '14082026', '2': '02092026'})
        self.assertEqual(col('T1RXXXXG6S'), {'1': '125'})   # номер РК невідомий
        self.assertEqual(col('T1RXXXXG7'), {'1': '50000.00', '2': '-1500.50'})
        self.assertEqual(col('T1RXXXXG8'), {'1': '10000.00', '2': '-300.10'})
        self.assertEqual(col('T1RXXXXG9S')['1'],
                         'Продавець не зареєстрував ПН в ЄРПН у граничний строк')
        self.assertEqual(body.findtext('HEXPL'), '3')
        self.assertEqual(body.findtext('HNPDV'), '123456789012')

    def test_d6_fop_uses_f_form(self):
        self.company.write({'vat': '3123456789'})
        with patch.object(type(self.env['l10n_ua.vat.declaration']), '_is_fop_declaration',
                          return_value=True):
            decl = self._declaration()
            self._complaints(decl)
            decl.d6_attached_sheets = 0      # HEXPL необов'язковий
            main, d6 = self._generate(decl)
            _schema('F0200126.xsd').assertValid(main)
            _schema('F0215826.xsd').assertValid(d6)
        self.assertIn('F0215826', decl.d6_xml_filename)
        self.assertIsNone(d6.find('DECLARBODY/HEXPL'))
        self.assertEqual(d6.findtext('DECLARBODY/HTIN'), '3123456789')

    def test_no_rows_no_d6(self):
        decl = self._declaration()
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        self.assertFalse(decl.d6_xml_file)
        self.assertIsNone(main.find('DECLARBODY/HD6'))
        self.assertNotIn('J0215826', base64.b64decode(decl.xml_file).decode('cp1251'))

    def test_validation_errors(self):
        decl = self._declaration()
        decl.write({'d6_line_ids': [(0, 0, {
            'doc_kind': 'pn', 'partner_name': 'ТОВ Без ІПН', 'partner_ipn': '12345',
            'doc_date': date(2026, 9, 1), 'description': '   '})]})
        with self.assertRaises(UserError) as err:
            decl.action_generate_xml()
        message = str(err.exception)
        self.assertIn('Д6: ІПН контрагента (12 цифр): ТОВ Без ІПН', message)
        self.assertIn('опис помилки', message)

    def test_tax_invoice_fills_row(self):
        invoice = self.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'received', 'doc_type': 'pn', 'number': '77',
            'date': date(2026, 8, 20), 'partner_id': self.supplier.id,
            'company_id': self.company.id,
        })
        decl = self._declaration()
        with Form(decl) as form:
            with form.d6_line_ids.new() as line:
                line.tax_invoice_id = invoice
                self.assertEqual(line.partner_name, self.supplier.name)
                self.assertEqual(line.partner_ipn, '987654321098')
                self.assertEqual(line.doc_number, '77')
                self.assertEqual(line.doc_date, date(2026, 8, 20))
                line.description = 'Помилка в коді УКТЗЕД'
        self.assertEqual(decl.d6_line_ids.doc_kind, 'pn')
