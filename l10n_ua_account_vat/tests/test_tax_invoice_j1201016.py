"""ПН у форматі J1201016 — валідна за офіційною XSD (СКЗ 1.34.0.0)."""
import base64
import os
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .common_pn import set_pn_requisites

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')


@tagged('post_install', '-at_install')
class TestTaxInvoiceJ1201016(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.sudo().group_ids |= cls.env.ref('l10n_ua_account_base.group_ua_user')
        cls.company = cls.env.company
        cls.company.write({'l10n_ua_is_vat_payer': True, 'l10n_ua_vat_ipn': '123456789012'})
        set_pn_requisites(cls.env, cls.company)
        cls.buyer = cls.env['res.partner'].create({
            'name': 'ТОВ «Покупець»', 'is_company': True, 'ipn': '987654321098', 'edrpou': '87654300'})
        cls.kg = cls.env.ref('uom.product_uom_kgm')
        cls.schema = etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, 'J1201016.xsd')))

    def _pn(self, partner, lines, **vals):
        return self.env['l10n_ua.tax.invoice'].create(dict({
            'doc_type': 'pn', 'invoice_type': 'issued', 'number': '2026/0000042', 'date': date(2026, 10, 12),
            'partner_id': partner.id, 'company_id': self.company.id,
            'line_ids': [(0, 0, line) for line in lines]}, **vals))

    def _xml(self, pn):
        pn.action_generate_xml()
        # Odoo 20: BinaryValue — сирі байти в .content.
        data = pn.file_xml.content
        root = etree.fromstring(data)
        self.schema.assertValid(root)
        return root, data

    def test_vat_payer_buyer(self):
        pn = self._pn(self.buyer, [
            {'name': 'Пшениця 3 клас', 'uktzed_code': '1001990000', 'quantity': 22.5, 'uom_id': self.kg.id,
             'price_unit': 7.37, 'vat_rate': '14'},
            {'name': 'Послуги сушіння', 'dkpp_code': '01.63.10-00.00', 'quantity': 1, 'price_unit': 1000.0,
             'vat_rate': '20'},
        ])
        root, data = self._xml(pn)
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('HNUM'), '42')
        self.assertEqual(body.findtext('HKSEL'), '123456789012')
        self.assertEqual(body.findtext('HKBUY'), '987654321098')
        self.assertEqual(body.findtext('HTINBUY'), '87654300')
        self.assertIsNone(body.find('HTYPR'))
        self.assertEqual(body.findtext('R01G14'), '165.83')          # 22,5 × 7,37
        self.assertEqual(body.findtext('R03G14'), '23.22')
        self.assertEqual(body.findtext('R01G7'), '1000.00')
        self.assertEqual(body.findtext('R03G7'), '200.00')
        self.assertEqual(body.findtext('R03G11'), '223.22')
        self.assertEqual(body.findtext('R04G11'), '1389.05')
        self.assertEqual(body.find('RXXXXG105_2S').text, '0301')
        self.assertEqual(root.findtext('DECLARHEAD/C_DOC_CNT'), '42')
        self.assertTrue(pn.file_xml_name.startswith('2650'))         # ім'я за стандартом ДПС
        self.assertIn('J1201016', pn.file_xml_name)

    def test_non_payer_and_export(self):
        individual = self.env['res.partner'].create({'name': 'Коваль Марія Іванівна', 'ipn': '3124567896'})
        pn = self._pn(individual, [{'name': 'Пшениця 3 клас', 'uktzed_code': '1001990000', 'quantity': 924,
                                    'uom_id': self.kg.id, 'price_unit': 7.4561, 'vat_rate': '14'}],
                      non_payer_reason='02')
        root, _data = self._xml(pn)
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('HORIG1'), '1')
        self.assertEqual(body.findtext('HTYPR'), '02')
        self.assertEqual(body.findtext('HKBUY'), '100000000000')
        self.assertEqual(body.findtext('HNAMEBUY'), 'Неплатник')

        foreign = self.env['res.partner'].create({
            'name': 'Alpen Saaten GmbH', 'is_company': True, 'country_id': self.env.ref('base.at').id})
        export = self._pn(foreign, [{'name': 'Pumpkin seeds', 'uktzed_code': '1207999700', 'quantity': 20000,
                                     'uom_id': self.kg.id, 'price_unit': 156.24, 'vat_rate': '0'}],
                          non_payer_reason='07', number='2026/0000043')
        with self.assertRaises(UserError):
            export.action_generate_xml()                       # без контракту й МД
        export.write({'contract_number': 'EXP-1/2026', 'contract_date': date(2026, 1, 15),
                      'customs_number': '26UA101020004517U1', 'customs_date': date(2026, 10, 12)})
        root, _data = self._xml(export)
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('HTYPR'), '07')
        self.assertEqual(body.findtext('HKBUY'), '300000000000')
        self.assertEqual(body.findtext('HNAMEBUY'), 'Alpen Saaten GmbH')
        self.assertEqual(body.findtext('RXXXXG008'), '901')
        self.assertEqual(body.findtext('R01G9'), '3124800.00')
        self.assertEqual(body.findtext('R002G2S'), '26UA101020004517U1')

    def test_missing_requisites(self):
        self.company.l10n_ua_vat_signer_rnokpp = False
        pn = self._pn(self.buyer, [{'name': 'Товар', 'uktzed_code': '1001990000', 'quantity': 1,
                                    'price_unit': 10, 'vat_rate': '20'}])
        pn.signer_rnokpp = False
        with self.assertRaises(UserError):
            pn.action_generate_xml()
