"""Рядки 4.x (п. 198.5/199.1), 6.x/13.x (послуги нерезидента), Д1 табл. 1.2.4 і Д5."""

import base64
from datetime import date

from lxml import etree

from odoo.tests import tagged

from .test_vat_declaration_xml import VatDeclarationCase, _schema


@tagged('post_install', '-at_install')
class TestVatDeclarationD5(VatDeclarationCase):

    def _issued(self, register, number, day, base, vat, month=9, partner=None, state='draft',
                doc_type='pn', **inv_vals):
        partner = partner or self.customer
        if not self.company.partner_id.ipn:
            self.company.partner_id.ipn = '123456789012'   # ПН «на себе»
        invoice = self.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'issued', 'company_id': self.company.id, 'partner_id': partner.id,
            'doc_type': doc_type, 'number': number, 'date': date(2026, month, day), **inv_vals})
        if state == 'registered':
            invoice.state = 'registered'
        rate = {'base_20': base, 'vat_20': vat} if vat else {'base_exempt': base}
        self.env['l10n_ua.vat.register.line'].create({
            'register_id': register.id, 'date': invoice.date, 'doc_type': doc_type,
            'tax_invoice_id': invoice.id, 'partner_id': partner.id,
            'invoice_number': number, 'invoice_date': invoice.date,
            'base_amount': base, 'vat_amount': vat, **rate})
        return invoice

    def test_special_basis_and_nonresident_rows(self):
        self._issued(self.issued, '51', 15, 1000.0, 200.0, partner=self.company.partner_id,
                     vat_special_basis='198_5')
        nonres = self.env['res.partner'].create({'name': 'Google Ireland', 'ipn': '500000000000'})
        self._issued(self.issued, '52', 16, 3000.0, 600.0, partner=nonres, state='registered')
        decl = self._declaration()
        self.assertEqual((decl.line_4_1_base, decl.line_4_1_vat), (1000, 200))
        self.assertEqual((decl.line_6_1_base, decl.line_6_1_vat), (3000, 600))
        self.assertEqual((decl.line_13_1_base, decl.line_13_1_vat), (3000, 600))
        self.assertEqual(decl.line_1_1_vat, 20000)          # без 4.x і 6.x
        self.assertEqual(decl.line_9_vat, 20000 + 200 + 600)
        self.assertEqual(decl.line_17_vat, 8800 + 600)
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        _schema('J0200126.xsd').assertValid(main)
        body = main.find('DECLARBODY')
        self.assertEqual([body.findtext(t) for t in ('R41GB', 'R61GB', 'R131GB')],
                         ['200', '600', '600'])
        d1 = etree.fromstring(base64.b64decode(decl.d1_xml_file))
        _schema('J0200526.xsd').assertValid(d1)
        # Незареєстрована ПН за п. 198.5 — таблиця 1.1.1 з ознакою «+».
        d1body = d1.find('DECLARBODY')
        self.assertEqual(d1body.findtext('T111RXXXXG4S'), '51')
        self.assertEqual(d1body.findtext('T111RXXXXG5'), '1')

    def test_annual_share_in_december(self):
        sep = self._declaration()
        self.assertEqual(sep.state, 'calculated')
        dec_period = self.env['l10n_ua.tax.period'].create({
            'name': 'Грудень 2026', 'date_start': date(2026, 12, 1),
            'date_end': date(2026, 12, 31), 'period_type': 'month', 'month': 12,
            'year': 2026, 'quarter': 4, 'company_id': self.company.id,
        })
        Register = self.env['l10n_ua.vat.register']
        issued = Register.create({'register_type': 'issued', 'period_id': dec_period.id,
                                  'company_id': self.company.id})
        Register.create({'register_type': 'received', 'period_id': dec_period.id,
                         'company_id': self.company.id})
        self._issued(issued, '90', 10, 79999.60, 15999.92, month=12, state='registered')
        self._issued(issued, '91', 11, 20000.0, 0.0, month=12, state='registered')
        # РК річного перерахунку до ПН за п. 199.1 (не зареєстрована → Д1 табл. 1.2.4).
        original = self._issued(issued, '70', 1, 5000.0, 1000.0, month=12,
                                partner=self.company.partner_id, state='registered',
                                vat_special_basis='199_1')
        self._issued(issued, '92', 31, 500.0, 100.0, month=12,
                     partner=self.company.partner_id, doc_type='rk',
                     original_invoice_id=original.id, vat_199_recalc=True)
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': dec_period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890'})
        decl.action_calculate()
        self.assertEqual(decl.d5_share_mode, 'annual')
        # Рік: вересень 100000 + грудень 80000 (оподатк.) + 20000 (звільнені)
        # + ПН 199.1 і її РК (рядки 4.x — у частку не входять).
        self.assertEqual(decl.d5_total_volume, 200000)
        self.assertEqual(decl.d5_taxable_volume, 180000)
        self.assertEqual(decl.d5_taxable_share, 90.0)
        self.assertEqual((decl.line_4_1_vat, decl.line_4_1_1_vat), (1000, 100))
        decl.vat_limit_amount = 10 ** 6
        decl.write({'d5_t3_g1': 1000, 'd5_t3_g7': 300, 'd5_t3_g11': 400})
        self.assertEqual(decl.d5_t3_g13, 900)
        decl.action_generate_xml()
        d5 = etree.fromstring(base64.b64decode(decl.d5_xml_file))
        _schema('J0215726.xsd').assertValid(d5)
        body = d5.find('DECLARBODY')
        self.assertEqual([body.findtext(t) for t in ('R011G4', 'R011G5', 'R011G6', 'R011G7')],
                         ['200000', '180000', '90.00', '10.00'])
        self.assertEqual(body.findtext('T2RXXXXG3S'), '70')
        self.assertEqual(body.findtext('T2RXXXXG5S'), '92')
        self.assertEqual(body.findtext('T2RXXXXG9'), '100.00')
        self.assertEqual(body.findtext('R041G13'), '900')
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        _schema('J0200126.xsd').assertValid(main)
        self.assertEqual(main.findtext('DECLARBODY/HD5'), '1')
        d1 = etree.fromstring(base64.b64decode(decl.d1_xml_file))
        _schema('J0200526.xsd').assertValid(d1)
        self.assertEqual(d1.findtext('DECLARBODY/T124RXXXXG4S'), '92')
        self.assertEqual(d1.findtext('DECLARBODY/R0124G7'), '100')

    def test_no_d5_without_mixed_operations(self):
        decl = self._declaration()
        self.assertFalse(decl.d5_share_mode)
        decl.action_generate_xml()
        self.assertFalse(decl.d5_xml_file)
