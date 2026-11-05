from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock_account.tests.test_anglo_saxon_valuation_reconciliation_common import (
    ValuationReconciliationTestCommon,
)

CLEARANCE = date(2026, 9, 3)


@tagged('post_install', '-at_install')
class TestImportDeclaration(ValuationReconciliationTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.l10n_ua_is_vat_payer = True
        cls.eur = cls.env.ref('base.EUR')
        cls.eur.active = True
        Rate = cls.env['res.currency.rate']
        Rate.search([('currency_id', '=', cls.eur.id), ('company_id', 'in', (cls.company.id, False))]).unlink()
        for day, rate in ((date(2026, 9, 1), 45.0), (CLEARANCE, 46.0)):
            Rate.create({'currency_id': cls.eur.id, 'name': day, 'rate': 1.0 / rate, 'company_id': cls.company.id})
        Account = cls.env['account.account']
        cls.customs_account = Account.create({
            'code': '377100', 'name': 'Розрахунки з митницею (test)', 'account_type': 'asset_current',
            'reconcile': True})
        cls.vat_account = Account.create({
            'code': '644100', 'name': 'Податковий кредит (test)', 'account_type': 'liability_current'})
        cls.customs = cls.env['res.partner'].create({'name': 'Волинська митниця (test)', 'is_company': True})
        cls.company.write({
            'l10n_ua_import_customs_account_id': cls.customs_account.id,
            'l10n_ua_import_vat_account_id': cls.vat_account.id,
            'l10n_ua_import_customs_partner_id': cls.customs.id,
            'l10n_ua_import_journal_id': cls.company_data['default_journal_misc'].id,
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Maschinenbau GmbH (test)', 'is_company': True, 'country_id': cls.env.ref('base.de').id})
        # договір веде відділ продажів (права l10n_ua_agreement)
        cls.env.user.sudo().group_ids |= cls.env.ref('sales_team.group_sale_salesman_all_leads') \
            | cls.env.ref('l10n_ua_account_base.group_ua_manager')
        cls.contract = cls.env['l10n_ua.agreement'].create({
            'code': 'IMP-7/2026', 'name': 'Import contract', 'direction': 'purchase', 'partner_id': cls.vendor.id,
            'currency_id': cls.eur.id, 'l10n_ua_foreign_trade': True,
            'l10n_ua_incoterm_id': cls.env.ref('account.incoterm_DAP').id})
        cls.pump = cls.env['product.product'].create({
            'name': 'Pump (test)', 'is_storable': True, 'categ_id': cls.stock_account_product_categ.id})

    def _purchase(self):
        """Закупівля в євро: надходження й рахунок постачальника на дату МД
        (Дт 281 Кт 632 за курсом НБУ на дату рахунку)."""
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id, 'currency_id': self.eur.id, 'date_order': CLEARANCE,
            'order_line': [(0, 0, {'product_id': self.pump.id, 'product_qty': 10.0, 'price_unit': 100.0,
                                   'tax_ids': [(6, 0, [])]})]})
        order.button_confirm()
        picking = order.picking_ids
        picking.move_ids.quantity = 10.0
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        order.action_create_invoice()
        bill = order.invoice_ids
        bill.write({'invoice_date': CLEARANCE, 'date': CLEARANCE, 'l10n_ua_agreement_id': self.contract.id})
        bill.action_post()
        return picking, bill

    def _declaration(self, **values):
        picking, bill = self._purchase()
        return self.env['l10n_ua.import.declaration'].create({
            'name': '26UA205000%07dU' % bill.id,
            'date': CLEARANCE,
            'partner_id': self.vendor.id,
            'agreement_id': self.contract.id,
            'bill_ids': [(6, 0, bill.ids)],
            'picking_ids': [(6, 0, picking.ids)],
            'duty_amount': 4600.0,
            'fee_amount': 100.0,
            **values,
        })

    def test_amounts(self):
        declaration = self._declaration(excise_amount=400.0)
        self.assertEqual(declaration.currency_id, self.eur)
        self.assertEqual(declaration.customs_office_id, self.customs)
        self.assertAlmostEqual(declaration.invoice_value, 1000.0)
        self.assertAlmostEqual(declaration.exchange_rate, 46.0)
        self.assertAlmostEqual(declaration.customs_value, 46000.0)          # 1 000 € × 46,00
        # база ПДВ — митна вартість + мито + акциз, збори не входять (п. 190.1)
        self.assertAlmostEqual(declaration.vat_base, 51000.0)
        self.assertAlmostEqual(declaration.vat_amount, 10200.0)
        self.assertAlmostEqual(declaration.amount_customs_total, 4600.0 + 400.0 + 100.0 + 10200.0)
        self.assertEqual(declaration.vat_payment_date, CLEARANCE)
        self.assertFalse(declaration.bill_date_warning)

    def test_post_landed_cost_vat_and_tax_credit(self):
        declaration = self._declaration()
        move = declaration.picking_ids.move_ids
        self.assertAlmostEqual(move.value, 46000.0)
        declaration.action_post()
        self.assertEqual(declaration.state, 'posted')
        # мито й збори — у собівартість: Дт 281 (оцінка запасів) Кт 377 з митницею
        landed_cost = declaration.landed_cost_ids
        self.assertEqual(landed_cost.state, 'done')
        self.assertAlmostEqual(landed_cost.amount_total, 4700.0)
        lines = landed_cost.account_move_id.line_ids
        credit = lines.filtered(lambda l: l.account_id == self.customs_account)
        self.assertAlmostEqual(sum(credit.mapped('credit')), 4700.0)
        self.assertEqual(credit.partner_id, self.customs)
        stock = lines.filtered(lambda l: l.account_id == self.company_data['default_account_stock_valuation'])
        self.assertAlmostEqual(sum(stock.mapped('debit')), 4700.0)
        self.assertAlmostEqual(move.value, 50700.0)
        # ПДВ з МД: Дт 6441 Кт 377
        vat_lines = declaration.move_id.line_ids
        self.assertEqual(declaration.move_id.state, 'posted')
        self.assertEqual(declaration.move_id.date, CLEARANCE)
        self.assertAlmostEqual(vat_lines.filtered(lambda l: l.account_id == self.vat_account).debit, 10120.0)
        self.assertAlmostEqual(vat_lines.filtered(lambda l: l.account_id == self.customs_account).credit, 10120.0)
        # МД — підстава для податкового кредиту (п. 201.12)
        document = declaration.tax_invoice_id
        self.assertEqual(document.invoice_type, 'received')
        self.assertTrue(document.is_import)
        self.assertEqual(document.number, declaration.name)
        self.assertEqual(document.date, CLEARANCE)
        self.assertEqual(document.partner_id, self.customs)
        self.assertAlmostEqual(document.total_base, 50600.0)
        self.assertAlmostEqual(document.total_vat, 10120.0)
        self.assertTrue(document.name.startswith('МД '))
        # усього митниці: 4 600 + 100 + 10 120
        balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.customs_account.id), ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance, -14820.0)

    def test_vat_return_rows(self):
        declaration = self._declaration()
        declaration.action_post()
        period = self.env['l10n_ua.tax.period'].search([
            ('company_id', '=', self.company.id), ('date_start', '=', date(2026, 9, 1)),
            ('period_type', '=', 'month')], limit=1) or self.env['l10n_ua.tax.period'].create({
            'name': 'Вересень 2026 (test)', 'date_start': date(2026, 9, 1), 'date_end': date(2026, 9, 30),
            'period_type': 'month', 'month': 9, 'year': 2026, 'quarter': 3, 'company_id': self.company.id})
        register = self.env['l10n_ua.vat.register'].create({
            'period_id': period.id, 'register_type': 'received', 'company_id': self.company.id})
        register.action_compute()
        self.assertEqual(register.line_ids.tax_invoice_id, declaration.tax_invoice_id)
        vat_return = self.env['l10n_ua.vat.declaration'].create({
            'period_id': period.id, 'company_id': self.company.id})
        vat_return.action_calculate()
        self.assertEqual(vat_return.line_11_1_base, 50600)
        self.assertEqual(vat_return.line_11_1_vat, 10120)
        self.assertEqual(vat_return.line_10_1_vat, 0)
        self.assertFalse(vat_return._d1_lines())                         # імпорт не йде в Д1
        # ліміт ЄРПН: ПДВ з МД — ΣМитноПДВ
        register.action_confirm()
        limit = self.env['l10n_ua.vat.erpn.limit'].create({'date': date(2026, 9, 30)})
        limit.action_calculate_from_registers()
        registers = self.env['l10n_ua.vat.register'].search([
            ('register_type', '=', 'received'), ('state', '=', 'confirmed'), ('company_id', '=', self.company.id)])
        import_vat = sum(registers.line_ids.filtered(lambda l: l.tax_invoice_id.is_import).mapped('vat_amount'))
        self.assertGreaterEqual(import_vat, 10120.0)
        self.assertAlmostEqual(limit.amount_import_vat, import_vat)
        self.assertAlmostEqual(limit.amount_received_vat, sum(registers.mapped('total_vat')) - import_vat)

    def test_cancel_reverses_postings(self):
        declaration = self._declaration()
        move = declaration.picking_ids.move_ids
        declaration.action_post()
        declaration.action_cancel()
        self.assertEqual(declaration.state, 'cancel')
        self.assertEqual(len(declaration.landed_cost_ids), 2)
        self.assertAlmostEqual(move.value, 46000.0)
        self.assertTrue(declaration.move_id.reversal_move_ids)          # сторно ПДВ
        self.assertEqual(declaration.tax_invoice_id.state, 'cancelled')
        balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.customs_account.id), ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance, 0.0)
        declaration.action_draft()
        self.assertEqual(declaration.state, 'draft')
        self.assertFalse(declaration.tax_invoice_id)

    def test_post_checks(self):
        declaration = self._declaration()
        declaration.name = 'MD-1'
        with self.assertRaises(UserError):
            declaration.action_post()
        declaration.write({'name': '26UA205000000001U9', 'picking_ids': [(5, 0, 0)]})
        with self.assertRaises(UserError):                               # мито без надходжень
            declaration.action_post()

    def test_exempt_without_duty(self):
        declaration = self._declaration(duty_amount=0.0, fee_amount=0.0, vat_rate='exempt')
        declaration.picking_ids = False
        declaration.action_post()
        self.assertEqual(declaration.state, 'posted')
        self.assertFalse(declaration.landed_cost_ids)
        self.assertFalse(declaration.move_id)
        self.assertFalse(declaration.tax_invoice_id)
