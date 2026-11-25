"""#560, КП1–КП3: коригування звільнених операцій (р.5.1.1, R511GA)."""

import base64
import os
from datetime import date

from lxml import etree

from odoo.tests import TransactionCase, tagged

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')


@tagged('post_install', '-at_install')
class TestVatDeclarationExemptAdjustment(TransactionCase):

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
            {'name': 'ТОВ Покупець #560', 'ipn': '222222222222'})
        cls.period = cls.env['l10n_ua.tax.period'].create({
            'name': 'Жовтень 2026 (#560)', 'date_start': date(2026, 10, 1),
            'date_end': date(2026, 10, 31), 'period_type': 'month', 'month': 10,
            'year': 2026, 'quarter': 4, 'company_id': cls.company.id,
        })
        Register = cls.env['l10n_ua.vat.register']
        cls.issued = Register.create({'register_type': 'issued', 'period_id': cls.period.id,
                                      'company_id': cls.company.id})
        Register.create({'register_type': 'received', 'period_id': cls.period.id,
                         'company_id': cls.company.id})
        cls.Line = cls.env['l10n_ua.vat.register.line']
        pn = cls._invoice('pn', '201', 300.0, 'exempt')
        cls._register_line(pn, 'pn', base_exempt=300.0)
        # РК до ПН «звільнено» −50 і звичайне РК 20 % −100.
        rk = cls._invoice('rk', '202', -50.0, 'exempt')
        cls.rk_exempt = cls._register_line(rk, 'rk', base_exempt=-50.0)
        rk20 = cls._invoice('rk', '203', -100.0, '20')
        cls._register_line(rk20, 'rk', base_20=-100.0, vat_20=-20.0)

    @classmethod
    def _invoice(cls, doc_type, number, price, rate):
        # РК на зменшення без реєстрації в ЄРПН XML не пропускає — реєструємо.
        return cls.env['l10n_ua.tax.invoice'].create({
            'state': 'registered',
            'invoice_type': 'issued', 'doc_type': doc_type, 'number': number,
            'date': date(2026, 10, 15), 'partner_id': cls.customer.id,
            'company_id': cls.company.id,
            'line_ids': [(0, 0, {'name': 'Ліки', 'quantity': 1.0, 'price_unit': price,
                                 'vat_rate': rate,
                                 'benefit_code': '14060509' if rate == 'exempt' else False})],
        })

    @classmethod
    def _register_line(cls, inv, doc_type, **amounts):
        base = sum(v for k, v in amounts.items() if k.startswith('base'))
        vat = sum(v for k, v in amounts.items() if k.startswith('vat'))
        return cls.Line.create(dict(
            amounts, register_id=cls.issued.id, date=date(2026, 10, 15), doc_type=doc_type,
            partner_id=cls.customer.id, tax_invoice_id=inv.id,
            base_amount=base, vat_amount=vat))

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def _main_body(self, decl):
        decl.action_generate_xml()
        main = etree.fromstring(base64.b64decode(decl.xml_file))
        etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, 'J0200126.xsd'))).assertValid(main)
        return main.find('DECLARBODY')

    def test_kp1_exempt_adjustment(self):
        """КП1: ПН 300 + РК −50 → 5.1 = 250, 5.1.1 = −50, у 7.1 цих −50 немає."""
        decl = self._declaration()
        self.assertEqual(decl.line_5_1_base, 250)
        self.assertEqual(decl.line_5_1_1_base, -50)
        self.assertEqual(decl.line_5_base, 250)
        self.assertEqual(decl.line_7_1_base, -100)
        self.assertEqual(decl.line_7_1_vat, -20)
        body = self._main_body(decl)
        self.assertEqual(body.findtext('R511GA'), '-50')
        self.assertEqual(body.findtext('R51GA'), '250')

    def test_kp2_no_adjustment_no_tag(self):
        """КП2: без РК до звільнених операцій R511GA у XML немає."""
        self.rk_exempt.unlink()
        decl = self._declaration()
        self.assertEqual(decl.line_5_1_1_base, 0)
        self.assertEqual(decl.line_5_1_base, 300)
        self.assertIsNone(self._main_body(decl).find('R511GA'))

    def test_kp3_d4_table2_matches_5_1(self):
        """КП3: «Усього» гр.5 таблиці 2 Д4 = р.5.1 з урахуванням коригування."""
        decl = self._declaration()
        self.assertEqual(sum(decl.d4_t2_line_ids.mapped('supply_amount')), 250)
        self.assertFalse([p for p in decl._d4_check() if 'Д4' in p])

    def test_not_object_toggle_off_by_default(self):
        decl = self._declaration()
        self.assertFalse(decl.include_not_object_5)
