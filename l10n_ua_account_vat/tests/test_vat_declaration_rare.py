"""Рідкісні таблиці: Д1 1.3 (РЕЗ), Д2 1.1 (відшкодування з РЕЗ), Д2 2/3 (реорганізація)."""

import base64
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_vat_declaration_xml import VatDeclarationCase, _schema


@tagged('post_install', '-at_install')
class TestVatDeclarationRare(VatDeclarationCase):

    def test_rez_corrections_go_to_7_2_and_d1_table_1_3(self):
        decl = self._declaration()
        decl.write({'d1_t13_line_ids': [
            (0, 0, {'rk_date': date(2026, 9, 20), 'rk_number': '61', 'basis': '1',
                    'pn_date': date(2026, 6, 5), 'pn_number': '12', 'export_month': 6,
                    'export_year': 2026, 'base_amount': 1000, 'vat_20': 200}),
            (0, 0, {'rk_date': date(2026, 9, 21), 'rk_number': '62', 'basis': '2',
                    'pn_date': date(2026, 7, 5), 'pn_number': '13', 'export_month': 7,
                    'export_year': 2026, 'vat_14': 70}),
        ]})
        self.assertEqual((decl.line_7_2_2_base, decl.line_7_2_2_vat), (1000, 200))
        self.assertEqual(decl.line_7_2_3_vat, 70)
        self.assertEqual(decl.line_9_vat, 20000 + 270)
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        d1 = etree.fromstring(base64.b64decode(decl.d1_xml_file))
        _schema('J0200126.xsd').assertValid(main)
        _schema('J0200526.xsd').assertValid(d1)
        self.assertEqual(main.findtext('DECLARBODY/R722GB'), '200')
        body = d1.find('DECLARBODY')
        self.assertEqual([e.text for e in body.findall('T13RXXXXG4')], ['1', '2'])
        self.assertEqual(len(body.findall('T13RXXXXG9')), 1)   # лише РЕЗ 2
        self.assertEqual(body.findtext('R013G11'), '70')

    def test_reorganisation_tables_without_negative_value(self):
        decl = self._declaration()
        decl.write({'d2_reorg_line_ids': [
            (0, 0, {'kind': 'in', 'partner_ipn': '444444444444', 'amount': 5000,
                    'apply_month': 6, 'apply_year': 2026, 'confirmed_amount': 4500,
                    'act_date': date(2026, 9, 1), 'act_number': 'А-1'}),
        ]})
        decl.action_generate_xml()
        d2 = etree.fromstring(base64.b64decode(decl.d2_xml_file))
        _schema('J0215226.xsd').assertValid(d2)
        self.assertEqual(d2.findtext('DECLARBODY/R05G5'), '4500')
        self.assertEqual(d2.findtext('DECLARBODY/T3RXXXXG4A'), '6')

    def test_reorganised_payer_transfers_negative_value(self):
        self._add_received(self.supplier2, 3, 25000.0)
        decl = self._declaration()
        decl.vat_limit_amount = 10 ** 6
        decl.d2_line_ids[:1].from_reorg = True
        decl.write({'d2_reorg_line_ids': [
            (0, 0, {'kind': 'out', 'partner_ipn': '555555555555', 'amount': decl.line_21_vat,
                    'act_date': date(2026, 9, 30), 'act_number': 'ПА-7'}),
        ]})
        decl.action_generate_xml()
        d2 = etree.fromstring(base64.b64decode(decl.d2_xml_file))
        _schema('J0215226.xsd').assertValid(d2)
        body = d2.find('DECLARBODY')
        self.assertEqual(body.findtext('R03G2'), '13800')
        self.assertEqual(body.findtext('R04G3'), '13800')
        self.assertEqual(len(body.findall('T1RXXXXG7')), 1)

    def test_rez_refund_detail_must_match_column_9(self):
        decl = self._declaration()
        decl.write({'d2_rez_line_ids': [
            (0, 0, {'partner_ipn': '300000000000', 'credit_month': 8, 'credit_year': 2026,
                    'paid_month': 8, 'paid_year': 2026, 'amount': 900}),
        ]})
        with self.assertRaisesRegex(UserError, 'табл. 1.1'):
            decl.action_generate_xml()
