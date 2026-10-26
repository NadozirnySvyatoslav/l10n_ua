"""Коди УКТ ЗЕД / ДКПП у ПН — беруться з номенклатури (#254)."""
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from .common_pn import set_pn_requisites


@tagged('post_install', '-at_install', 'l10n_ua_account_vat')
class TestTaxInvoiceProductCodes(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({'l10n_ua_is_vat_payer': True, 'l10n_ua_vat_ipn': '123456789012'})
        set_pn_requisites(cls.env, cls.env.company)
        cls.customer = cls.env['res.partner'].create({'name': 'Покупець кодів', 'ipn': '987654321098',
                                                      'is_company': True})
        cls.vat_20 = cls.env['account.tax'].create({
            'name': 'ПДВ 20% (коди)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id,
        })
        cls.goods = cls.env['product.product'].create({
            'name': 'Ноутбук', 'type': 'consu', 'uktzed_code': '8471.30.00.00',
        })
        cls.service = cls.env['product.product'].create({
            'name': 'Розробка ПЗ', 'type': 'service', 'dkpp_code': '62.01.11-00.00',
        })
        cls.uncoded = cls.env['product.product'].create({
            'name': 'Без коду', 'type': 'consu',
        })

    def _tax_invoice(self, products):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_date': '2025-05-05',
            'date': '2025-05-05',
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': product.name,
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [(6, 0, self.vat_20.ids)],
            }) for product in products],
        })
        move.action_post()
        move.action_create_tax_invoice()
        return self.env['l10n_ua.tax.invoice'].search([('move_id', '=', move.id)], limit=1)

    def test_goods_line_carries_uktzed(self):
        """Головна регресія #254: код читався через hasattr із неіснуючого
        поля, тож гр. 3.1 виходила порожньою завжди."""
        line = self._tax_invoice(self.goods).line_ids
        self.assertEqual(line.uktzed_code, '8471300000')
        self.assertFalse(line.dkpp_code)

    def test_service_line_carries_dkpp(self):
        line = self._tax_invoice(self.service).line_ids
        self.assertEqual(line.dkpp_code, '62.01.11-00.00')
        self.assertFalse(line.uktzed_code)

    def test_each_line_gets_its_own_code(self):
        tax_invoice = self._tax_invoice(self.goods + self.service)
        by_name = {line.name: line for line in tax_invoice.line_ids}
        self.assertEqual(by_name['Ноутбук'].uktzed_code, '8471300000')
        self.assertFalse(by_name['Ноутбук'].dkpp_code)
        self.assertEqual(by_name['Розробка ПЗ'].dkpp_code, '62.01.11-00.00')
        self.assertFalse(by_name['Розробка ПЗ'].uktzed_code)

    def test_xml_refuses_a_line_without_a_code(self):
        """ЄРПН не зареєструє рядок без коду — краще впасти тут, ніж у квитанції."""
        tax_invoice = self._tax_invoice(self.uncoded)
        with self.assertRaises(UserError):
            tax_invoice.action_generate_xml()

    def test_xml_carries_the_codes(self):
        tax_invoice = self._tax_invoice(self.goods + self.service)
        xml = tax_invoice._render_j1201016().decode('windows-1251')
        self.assertIn('<RXXXXG4 ROWNUM="1">8471300000</RXXXXG4>', xml)
        self.assertIn('<RXXXXG33 ROWNUM="2">62.01.11-00.00</RXXXXG33>', xml)
