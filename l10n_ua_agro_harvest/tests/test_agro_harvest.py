from datetime import date, datetime

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_agro_harvest.models.harvest_receipt import duval_weight


@tagged('post_install', '-at_install')
class TestAgroHarvest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.wheat = cls.env.ref('l10n_ua_agro_base.crop_wheat_winter')
        categ = cls.env['product.category'].create({'name': 'Сільгосппродукція (тест)'})
        if 'property_cost_method' in categ._fields:
            # з l10n_ua_agro_account врожай не оцінюється за стандартною ціною (#603)
            categ.property_cost_method = 'average'
        cls.grain = cls.env['product.product'].create({
            'name': 'Пшениця (тест)', 'is_storable': True, 'tracking': 'lot', 'categ_id': categ.id,
            'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.wheat.product_id = cls.grain
        season = cls.env['l10n_ua.agro.season'].create({
            'year': 2098, 'date_start': date(2097, 8, 1), 'date_end': date(2098, 12, 31)})
        cls.field = cls.env['l10n_ua.agro.field'].create({'name': 'Велике', 'code': 'H-01', 'area': 50.0})
        cls.planting = cls.env['l10n_ua.agro.planting'].create({
            'field_id': cls.field.id, 'season_id': season.id, 'crop_id': cls.wheat.id, 'area': 50.0})
        if 'l10n_ua.agro.fair.value' in cls.env:
            # з l10n_ua_agro_account кожне оприбуткування оцінюється (П(С)БО 30)
            cls._setup_valuation()

    @classmethod
    def _setup_valuation(cls):
        Account = cls.env['account.account']

        def account(code, account_type):
            return Account.search([('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1) \
                or Account.create({'code': code, 'name': code, 'account_type': account_type,
                                   'company_ids': [(6, 0, cls.company.ids)]})
        cls.company.write({
            'l10n_ua_agro_valuation_method': 'fair_value',
            'l10n_ua_agro_produce_account_id': account('27', 'asset_current').id,
            'l10n_ua_agro_recognition_income_account_id': account('710', 'income').id,
        })
        cls.env['l10n_ua.agro.fair.value'].create({
            'product_id': cls.grain.id, 'date': date(2098, 1, 1), 'price': 8000.0})

    def _receipt(self, gross, tare, moisture, impurity, **vals):
        return self.env['l10n_ua.agro.harvest.receipt'].create(dict({
            'date': datetime(2098, 7, 20, 10, 0), 'planting_id': self.planting.id,
            'vehicle': 'ВК 0001 АА', 'gross_weight': gross, 'tare_weight': tare,
            'moisture': moisture, 'impurity': impurity,
            'location_dest_id': self.warehouse.lot_stock_id.id}, **vals))

    def test_duval_formula(self):
        # 20 т, вологість 16 % і смітна 3 % при базисі 14 / 1
        self.assertAlmostEqual(duval_weight(20000, 16, 3, 14, 1), 20000 * 97 * 84 / (99 * 86), places=6)
        # краща за базис — без надбавки
        self.assertEqual(duval_weight(20000, 12, 0.5, 14, 1), 20000)

    def test_receive_into_batch_and_yield(self):
        self.assertEqual((self.wheat.base_moisture, self.wheat.base_impurity), (14.0, 1.0))
        r1 = self._receipt(35000, 14000, 16.0, 3.0, protein=12.5)
        self.assertEqual(r1.net_weight, 21000)
        self.assertEqual(r1.credit_weight, round(21000 * 97 * 84 / (99 * 86), 1))
        self.assertEqual(r1.product_id, self.grain)
        r1.action_done()
        r2 = self._receipt(34000, 14000, 13.5, 0.8)
        r2.action_done()
        self.assertEqual(r1.lot_id, r2.lot_id)
        lot = r1.lot_id
        self.assertEqual(lot.name, '2098-WHEAT_W-H-01')
        self.assertEqual(lot.l10n_ua_agro_planting_id, self.planting)
        self.assertAlmostEqual(lot.l10n_ua_agro_moisture, (16 * 21000 + 13.5 * 20000) / 41000, places=2)
        self.assertAlmostEqual(lot.l10n_ua_agro_protein, 12.5, places=2)
        total_kg = r1.credit_weight + r2.credit_weight
        quantity = self.grain.with_context(lot_id=lot.id, location=self.warehouse.lot_stock_id.id).qty_available
        # склад веде тонни з точністю 0,01 т
        self.assertAlmostEqual(quantity, r1.received_qty + r2.received_qty, places=2)
        self.assertAlmostEqual(r1.received_qty, round(r1.credit_weight / 1000, 2), places=2)
        self.assertAlmostEqual(self.planting.harvest_weight, total_kg / 1000, places=3)
        self.assertAlmostEqual(self.planting.harvest_yield, total_kg / 100 / 50, places=2)

        r2.action_cancel()
        self.assertEqual(r2.state, 'cancel')
        self.assertAlmostEqual(self.grain.with_context(lot_id=lot.id).qty_available,
                               r1.received_qty, places=2)

    def test_cannot_cancel_shipped_grain(self):
        r1 = self._receipt(30000, 10000, 14.0, 1.0)
        r1.action_done()
        # зерно продали: забираємо зі складу
        self.env['stock.quant']._update_available_quantity(
            self.grain, self.warehouse.lot_stock_id, -15.0, lot_id=r1.lot_id)
        with self.assertRaises(UserError):
            r1.action_cancel()

    def test_validation(self):
        with self.assertRaises(ValidationError):
            self._receipt(10000, 12000, 14.0, 1.0)
        empty = self._receipt(0, 0, 14.0, 1.0)
        with self.assertRaises(UserError):
            empty.action_done()

    def test_registers_and_quality_card(self):
        r1 = self._receipt(35000, 14000, 15.0, 2.0, vehicle='ВК 0001 АА', driver='Ковальчук П.')
        r2 = self._receipt(34000, 14000, 14.5, 1.5, vehicle='ВК 0001 АА', driver='Ковальчук П.',
                           date=datetime(2098, 7, 20, 13, 0))
        r3 = self._receipt(33000, 14200, 14.0, 1.0, vehicle='ВК 0002 АА', driver='Савчук О.')
        (r1 | r2 | r3).action_done()
        receipts = r1 | r2 | r3
        dispatch = receipts._print_registers(True)
        self.assertEqual(len(dispatch), 2)                      # дві машини
        first = [g for g in dispatch if g['key'][1] == 'ВК 0001 АА'][0]
        self.assertEqual(len(first['receipts']), 2)
        self.assertEqual(first['net'], 41000)
        received = receipts._print_registers(False)
        self.assertEqual(len(received), 1)                      # один день, один склад
        self.assertAlmostEqual(received[0]['credit'], sum(receipts.mapped('credit_weight')), places=1)
        Report = self.env['ir.actions.report']
        for ref in ('action_report_dispatch_register', 'action_report_receipt_register'):
            html, _fmt = Report._render_qweb_html('l10n_ua_agro_harvest.%s' % ref, receipts.ids)
            self.assertIn('ВК 0001 АА'.encode(), html)
        html, _fmt = Report._render_qweb_html('l10n_ua_agro_harvest.action_report_lot_quality', r1.lot_id.ids)
        self.assertIn(r1.lot_id.name.encode(), html)
