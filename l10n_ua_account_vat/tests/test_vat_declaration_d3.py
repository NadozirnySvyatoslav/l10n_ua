"""Д3 (J0299826 / F0299826): заяви про повернення бюджетного відшкодування, коштів СЕА ПДВ
і врахування реєстраційної суми при реорганізації."""

import base64
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .test_vat_declaration_xml import _schema


def _ua_iban(bban):
    """Коректний IBAN UA з 25 цифр BBAN (МФО + рахунок)."""
    num = int(bban + '3010' + '00')  # U=30, A=10
    return 'UA%02d%s' % (98 - num % 97, bban)


IBAN = _ua_iban('3052990000026007015025712')
IBAN2 = _ua_iban('3220010000026005310011111')
TREASURY = _ua_iban('8999980333119340000026001')


@tagged('post_install', '-at_install')
class TestVatDeclarationD3(TransactionCase):

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
        bank = cls.env['res.bank'].create({'name': 'АТ КБ «ПриватБанк»'})
        cls.company_bank = cls.env['res.partner.bank'].create({
            'partner_id': cls.company.partner_id.id, 'acc_number': IBAN,
            'bank_id': bank.id, 'sequence': -100,
        })

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def _add_received(self, partner, day, vat, month=9):
        self.env['l10n_ua.vat.register.line'].create({
            'register_id': self.received.id, 'date': date(2026, month, day),
            'partner_id': partner.id, 'base_amount': vat * 5, 'vat_amount': vat,
            'base_20': vat * 5, 'vat_20': vat})

    def _refund_declaration(self):
        self._add_received(self.supplier2, 3, 25000.0)
        decl = self._declaration()
        decl.vat_limit_amount = 100000
        self.assertEqual(decl.line_19_vat, 13800)
        decl.write({'line_20_2_1_vat': 4000, 'line_20_2_2_vat': 500})
        decl.d3_offset_line_ids = [(0, 0, {'kbk': '11010100', 'treasury_account': TREASURY,
                                           'amount': 300}),
                                   (0, 0, {'kbk': '18010500', 'treasury_account': TREASURY,
                                           'amount': 200})]
        return decl

    def test_no_d3_without_refund_or_applications(self):
        decl = self._declaration()
        decl.action_generate_xml()
        self.assertFalse(decl.d3_xml_file)
        self.assertIsNone(etree.fromstring(base64.b64decode(decl.xml_file)).find(
            'DECLARBODY/HD3'))

    def test_refund_to_bank_and_offset(self):
        decl = self._refund_declaration()
        # Рахунок за замовчуванням — банківський рахунок компанії.
        self.assertEqual(decl.d3_iban, IBAN)
        self.assertEqual(decl.d3_bank_name, 'АТ КБ «ПриватБанк»')
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        d3 = etree.fromstring(base64.b64decode(decl.d3_xml_file))
        _schema('J0200126.xsd').assertValid(main)
        _schema('J0299826.xsd').assertValid(d3)
        self.assertEqual(decl.d3_xml_filename, '26500012345678J0299826100000000110920262650.xml')
        self.assertEqual(main.findtext('DECLARBODY/HD3'), '1')
        self.assertIn(decl.d3_xml_filename[:-4].encode() + b'.XML',
                      base64.b64decode(decl.xml_file))
        self.assertIn(decl.xml_filename[:-4].encode() + b'.XML',
                      base64.b64decode(decl.d3_xml_file))
        body = d3.find('DECLARBODY')
        self.assertEqual([body.findtext(t) for t in ('R0303G2', 'R0303G3', 'R0304G2',
                                                      'R0305G1S', 'R0305G3S')],
                         ['9', '2026', '4000', IBAN, 'АТ КБ «ПриватБанк»'])
        self.assertEqual([e.text for e in body.findall('T1RXXXXG2')], ['11010100', '18010500'])
        self.assertEqual([e.text for e in body.findall('T1RXXXXG3S')], [TREASURY, TREASURY])
        self.assertEqual([e.text for e in body.findall('T1RXXXXG4')], ['300', '200'])
        self.assertEqual(body.findtext('R05G4'), '500')
        for tag in ('R0401G2', 'R06G1', 'R07G1', 'R08G1', 'T4RXXXXG2', 'T5RXXXXG2'):
            self.assertIsNone(body.find(tag))

    def test_offset_total_must_match_row_20_2_2(self):
        decl = self._refund_declaration()
        decl.d3_offset_line_ids[:1].amount = 250
        with self.assertRaisesRegex(UserError, 'таблиця 1.*20.2.2'):
            decl.action_generate_xml()

    def test_refund_requires_iban(self):
        decl = self._refund_declaration()
        decl.d3_iban = 'UA12345'
        with self.assertRaisesRegex(UserError, 'IBAN'):
            decl.action_generate_xml()

    def test_account_change_sea_and_reorganisation(self):
        decl = self._declaration()   # рядок 18 = 11200, відшкодування немає
        decl.write({
            'd3_change_month': 6, 'd3_change_year': 2026, 'd3_change_iban': IBAN2,
            'd3_change_bank_name': 'АТ «Ощадбанк»',
            'd3_sea_balance': 20000, 'd3_sea_tax_debt': 1000,
            'd3_sea_refund_amount': 5000, 'd3_sea_debt_amount': 1000,
            'd3_reorg_amount': 7000,
            'd3_reorg_line_ids': [(0, 0, {'partner_ipn': '333333333333', 'amount': 7000,
                                          'act_date': date(2026, 9, 15),
                                          'act_number': 'ПА-1'})],
            'd3_predecessor_line_ids': [(0, 0, {'partner_ipn': '444444444444',
                                                'amount_termination': 9000,
                                                'amount_confirmed': 8500,
                                                'act_date': date(2026, 8, 20),
                                                'act_number': '123/26'})],
        })
        self.assertEqual(decl.d3_sea_available, 20000 - 11200 - 1000)
        decl.action_generate_xml()
        d3 = etree.fromstring(base64.b64decode(decl.d3_xml_file))
        _schema('J0299826.xsd').assertValid(d3)
        body = d3.find('DECLARBODY')
        self.assertIsNone(body.find('R0303G2'))
        self.assertIsNone(body.find('R05G4'))
        values = {t: body.findtext(t) for t in (
            'R0401G2', 'R0401G3', 'R0402G2S', 'R0403G1S', 'R06G1', 'R06G2', 'R06G3', 'R06G4',
            'R07G1', 'R07G2S', 'R07G3S', 'R07G4', 'R08G1', 'T4RXXXXG2', 'T4RXXXXG3',
            'T4RXXXXG4D', 'T4RXXXXG5S', 'R09G3', 'T5RXXXXG2', 'T5RXXXXG3', 'T5RXXXXG4',
            'T5RXXXXG5D', 'T5RXXXXG6S', 'R010G4')}
        self.assertEqual(values, {
            'R0401G2': '6', 'R0401G3': '2026', 'R0402G2S': IBAN2, 'R0403G1S': 'АТ «Ощадбанк»',
            'R06G1': '20000', 'R06G2': '11200', 'R06G3': '1000', 'R06G4': '7800',
            'R07G1': '5000', 'R07G2S': 'АТ КБ «ПриватБанк»', 'R07G3S': IBAN, 'R07G4': '1000',
            'R08G1': '7000', 'T4RXXXXG2': '333333333333', 'T4RXXXXG3': '7000',
            'T4RXXXXG4D': '15092026', 'T4RXXXXG5S': 'ПА-1', 'R09G3': '7000',
            'T5RXXXXG2': '444444444444', 'T5RXXXXG3': '9000', 'T5RXXXXG4': '8500',
            'T5RXXXXG5D': '20082026', 'T5RXXXXG6S': '123/26', 'R010G4': '8500',
        })

    def test_sea_transfer_over_available_is_refused(self):
        decl = self._declaration()
        decl.write({'d3_sea_balance': 12000, 'd3_sea_refund_amount': 5000})
        with self.assertRaisesRegex(UserError, 'графу 4 таблиці 2'):
            decl.action_generate_xml()

    def test_fop_d3_uses_f_form(self):
        self.company.write({'vat': '3123456789'})
        with patch.object(type(self.env['l10n_ua.vat.declaration']), '_is_fop_declaration',
                          return_value=True):
            decl = self._refund_declaration()
            decl.action_generate_xml()
            _schema('F0200126.xsd').assertValid(etree.fromstring(base64.b64decode(decl.xml_file)))
            _schema('F0299826.xsd').assertValid(
                etree.fromstring(base64.b64decode(decl.d3_xml_file)))
        self.assertIn('F0299826', decl.d3_xml_filename)
