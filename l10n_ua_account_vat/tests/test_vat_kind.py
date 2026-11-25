"""#560: вид ставки ПДВ на податку відрізняє 0 % експорту, звільнення
та операції, що не є обʼєктом ПДВ."""
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_account_vat')
class TestVatKind(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.l10n_ua_is_vat_payer = True
        cls.customer = cls.env['res.partner'].create({'name': 'Покупець #560'})

        def tax(name, amount, kind=False):
            return cls.env['account.tax'].create({
                'name': name, 'amount': amount, 'amount_type': 'percent',
                'type_tax_use': 'sale', 'company_id': cls.env.company.id,
                'l10n_ua_vat_kind': kind,
            })
        cls.vat_20 = tax('ПДВ 20% (#560)', 20.0, 'taxable')
        cls.vat_14 = tax('ПДВ 14% (#560)', 14.0, 'taxable')
        cls.vat_7 = tax('ПДВ 7% (#560)', 7.0, 'taxable')
        cls.vat_0 = tax('ПДВ 0% (#560)', 0.0, 'zero')
        cls.vat_exempt = tax('0% Exempt (#560)', 0.0, 'exempt')
        cls.vat_not = tax('0% NS (#560)', 0.0, 'not_object')
        cls.vat_0_empty = tax('0% без виду (#560)', 0.0)

    def _tax_invoice(self, lines):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.customer.id,
            'invoice_date': '2025-05-05', 'date': '2025-05-05',
            'invoice_line_ids': [
                (0, 0, {'name': name, 'quantity': 1, 'price_unit': price,
                        'tax_ids': [(6, 0, tax.ids)]})
                for name, price, tax in lines],
        })
        move.action_post()
        move.action_create_tax_invoice()
        return self.env['l10n_ua.tax.invoice'].search([('move_id', '=', move.id)])

    def _codes(self, tax_invoice):
        return {l.name: (l.vat_rate, tax_invoice._pn_rate_code(l))
                for l in tax_invoice.line_ids}

    def test_tk1_exempt_gives_903(self):
        """ТК1: 0 % «Звільнено» — код 903, а не 902."""
        ti = self._tax_invoice([('звільнено', 300.0, self.vat_exempt)])
        self.assertEqual(self._codes(ti), {'звільнено': ('exempt', '903')})

    def test_tk2_not_object_not_in_pn(self):
        """ТК2: «Не обʼєкт» у ПН не потрапляє."""
        ti = self._tax_invoice([
            ('20', 1000.0, self.vat_20),
            ('не обʼєкт', 200.0, self.vat_not),
        ])
        self.assertEqual(ti.line_ids.mapped('name'), ['20'])

    def test_tk3_regress_rates(self):
        """ТК3: 20/14/7, 0 % експорт (902) і звільнено (903) в одній ПН."""
        ti = self._tax_invoice([
            ('20', 100.0, self.vat_20), ('14', 100.0, self.vat_14),
            ('7', 100.0, self.vat_7), ('0', 100.0, self.vat_0),
            ('звільнено', 100.0, self.vat_exempt),
        ])
        codes = self._codes(ti)
        self.assertEqual(codes['20'][0], '20')
        self.assertEqual(codes['14'][0], '14')
        self.assertEqual(codes['7'][0], '7')
        self.assertEqual(codes['0'][0], '0')
        self.assertEqual(codes['звільнено'], ('exempt', '903'))

    def test_empty_kind_falls_back_to_percent(self):
        """Порожній вид — стара логіка за відсотком: 0 % лишається ставкою 0."""
        Move = self.env['account.move']
        self.assertEqual(Move._l10n_ua_vat_rate_from_taxes(self.vat_0_empty), '0')
        self.assertFalse(Move._l10n_ua_is_not_object(self.vat_0_empty))
        ti = self._tax_invoice([('0', 100.0, self.vat_0_empty)])
        self.assertEqual(ti.line_ids.vat_rate, '0')

    def test_kind_inside_group(self):
        """Вид ставки працює і для податку всередині групи."""
        group = self.env['account.tax'].create({
            'name': 'Група NS (#560)', 'amount_type': 'group', 'type_tax_use': 'sale',
            'company_id': self.env.company.id,
            'children_tax_ids': [(6, 0, self.vat_not.ids)],
        })
        self.assertTrue(self.env['account.move']._l10n_ua_is_not_object(group))

    def test_tk5_fill_only_empty_by_xmlid(self):
        """ТК5: заповнення за xmlid шаблону, ручні правки не затираються."""
        company = self.env.company
        Tax = self.env['account.tax']
        stock_free = Tax.create({'name': 'stock free', 'amount': 0.0,
                                 'type_tax_use': 'sale', 'company_id': company.id})
        stock_not = Tax.create({'name': 'stock ns', 'amount': 0.0,
                                'type_tax_use': 'sale', 'company_id': company.id,
                                'l10n_ua_vat_kind': 'zero'})
        for tax, tmpl in ((stock_free, 'sale_tax_template_vat_free_psbo'),
                          (stock_not, 'sale_tax_template_vat_not_psbo')):
            self.env['ir.model.data'].create({
                'module': 'account', 'model': 'account.tax', 'res_id': tax.id,
                'name': '%s_%s' % (company.id, tmpl),
            })
        Tax._l10n_ua_fill_vat_kind(company)
        self.assertEqual(stock_free.l10n_ua_vat_kind, 'exempt')
        self.assertEqual(stock_not.l10n_ua_vat_kind, 'zero', 'ручну правку не затираємо')
