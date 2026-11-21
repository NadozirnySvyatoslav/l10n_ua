from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ua_agro_operations.tests.common import AgroOperationsTestCase


@tagged('post_install', '-at_install')
class TestAgroAccount(AgroOperationsTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_27 = cls._account('27', 'Продукція с/г виробництва', 'asset_current')
        cls.acc_710 = cls._account('710', 'Дохід від первісного визнання', 'income')
        cls.acc_940 = cls._account('940', 'Витрати від первісного визнання', 'expense')
        cls.acc_91 = cls._account('91', 'Загальновиробничі витрати', 'expense')
        cls.acc_685 = cls._account('685', 'Інші кредитори', 'liability_payable')
        cls.company.write({
            'l10n_ua_agro_produce_account_id': cls.acc_27.id,
            'l10n_ua_agro_recognition_income_account_id': cls.acc_710.id,
            'l10n_ua_agro_recognition_expense_account_id': cls.acc_940.id,
            'l10n_ua_agro_overhead_account_id': cls.acc_91.id,
        })
        # продукція — середньозважена собівартість, рахунок оцінки 27
        cls.produce_categ = cls.env['product.category'].create({'name': 'Сільгосппродукція (тест)'})
        cls.produce_categ.write({
            'property_cost_method': 'average',
            'property_stock_valuation_account_id': cls.acc_27.id,
        })
        cls.grain = cls.env['product.product'].create({
            'name': 'Пшениця (тест)', 'is_storable': True, 'categ_id': cls.produce_categ.id,
            'uom_id': cls.env.ref('uom.product_uom_kgm').id})
        cls.wheat.product_id = cls.grain
        cls.wheat.write({'base_moisture': 14.0, 'base_impurity': 1.0})
        cls.env['l10n_ua.agro.fair.value'].create({
            'product_id': cls.grain.id, 'date': date(2097, 7, 1), 'price': 8.0})
        cls.card.planned_yield = 50.0          # 50 ц/га
        # озимі під наступний сезон — незавершене виробництво
        season_next = cls.env['l10n_ua.agro.season'].create({
            'year': 2098, 'date_start': date(2097, 8, 1), 'date_end': date(2098, 12, 31)})
        field2 = cls.env['l10n_ua.agro.field'].create({'name': 'Біля лісу', 'code': 'T-02', 'area': 50.0})
        cls.planting_next = cls.env['l10n_ua.agro.planting'].create({
            'field_id': field2.id, 'season_id': season_next.id, 'crop_id': cls.wheat.id, 'area': 50.0})

    def _work(self):
        sow = self._order(self.op_sow, date=date(2096, 9, 25))
        sow.action_load_norms()
        sow.action_done()                     # 264 000 + 396 л × 55 = 285 780
        fert = self._order(self.op_fert, area=20.0, date=date(2097, 10, 1),
                           planting_id=self.planting_next.id)
        fert.action_load_norms()              # техкарти на 2098 немає — лише пальне за нормою
        fert.material_ids = [(0, 0, {'product_id': self.fertilizer.id, 'quantity': 3000.0})]
        fert.action_done()                    # 3 000 кг × 25 + 66 л × 55 = 78 630
        self.assertEqual(sow.material_amount + sow.fuel_amount, 285780.0)
        self.assertEqual(fert.material_amount + fert.fuel_amount, 78630.0)
        # непрямі: оренда землі на 23 без посіву і загальновиробничі на 91
        for debit, credit, amount in ((self.acc_231, self.acc_685, 50000.0), (self.acc_91, self.acc_685, 20000.0)):
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': self.journal.id, 'date': date(2097, 6, 30),
                'line_ids': [(0, 0, {'account_id': debit.id, 'debit': amount}),
                             (0, 0, {'account_id': credit.id, 'credit': amount})]})
            move.action_post()

    def _harvest(self):
        receipt = self.env['l10n_ua.agro.harvest.receipt'].create({
            'date': datetime(2097, 7, 20, 10), 'planting_id': self.planting.id,
            'gross_weight': 114000, 'tare_weight': 14000, 'moisture': 14.0, 'impurity': 1.0,
            'location_dest_id': self.warehouse.lot_stock_id.id})
        receipt.action_done()
        return receipt

    def _calculation(self):
        calc = self.env['l10n_ua.agro.cost.calculation'].create({'season_id': self.season.id})
        calc.action_compute()
        return calc

    def _balance(self, account, **domain):
        lines = self.env['account.move.line'].search(
            [('account_id', '=', account.id), ('parent_state', '=', 'posted')]
            + [(k, '=', v) for k, v in domain.items()])
        return sum(lines.mapped('balance'))

    def test_fair_value_recognition_and_closing(self):
        self._work()
        receipt = self._harvest()
        self.assertEqual(receipt.valuation_price, 8.0)
        self.assertEqual(receipt.valuation_amount, 800000.0)
        self.assertEqual(self._balance(self.acc_27), 800000.0)
        self.assertEqual(self._balance(self.acc_710), -800000.0)

        calc = self._calculation()
        line = calc.line_ids.filtered(lambda l: l.planting_id == self.planting)
        wip = calc.line_ids.filtered(lambda l: l.planting_id == self.planting_next)
        self.assertTrue(wip.is_wip)
        self.assertEqual(line.direct_cost, 285780.0)
        self.assertEqual(wip.direct_cost, 78630.0)
        self.assertEqual(calc.indirect_amount, 50000.0)
        self.assertEqual(calc.overhead_amount, 20000.0)
        self.assertAlmostEqual(line.allocated_cost + wip.allocated_cost, 50000.0, places=2)
        self.assertAlmostEqual(line.allocated_cost, round(50000 * 285780 / 364410, 2), places=2)
        self.assertAlmostEqual(line.overhead_cost + wip.overhead_cost, 20000.0, places=2)
        total = 285780.0 + line.allocated_cost + line.overhead_cost
        self.assertAlmostEqual(line.total_cost, total, places=2)
        self.assertAlmostEqual(line.closing_amount, total, places=2)
        self.assertAlmostEqual(line.cost_per_ton, total / 100.0, places=2)
        self.assertEqual(wip.closing_amount, 0.0)

        calc.action_post()
        self.assertAlmostEqual(self._balance(self.acc_940), total, places=2)
        self.assertAlmostEqual(self._balance(self.acc_91), 0.0, places=2)
        # на 23 лишилося лише незавершене виробництво озимих
        self.assertAlmostEqual(self._balance(self.acc_231), wip.total_cost, places=2)
        self.assertAlmostEqual(self._balance(self.acc_231, l10n_ua_agro_planting_id=self.planting_next.id),
                               wip.total_cost, places=2)
        with self.assertRaises(UserError):
            receipt.action_cancel()

        calc.action_cancel()
        self.assertAlmostEqual(self._balance(self.acc_940), 0.0, places=2)
        self.assertAlmostEqual(self._balance(self.acc_91), 20000.0, places=2)

    def test_planned_cost_method(self):
        self.company.l10n_ua_agro_valuation_method = 'planned_cost'
        self._work()
        # планова собівартість: (8 150 + 630) грн/га / 5 000 кг/га = 1,756 грн/кг
        self.assertAlmostEqual(self.card.planned_unit_cost, 1.756, places=4)
        receipt = self._harvest()
        self.assertEqual(receipt.valuation_amount, 175600.0)
        self.assertEqual(self._balance(self.acc_27), 175600.0)
        calc = self._calculation()
        line = calc.line_ids.filtered(lambda l: l.planting_id == self.planting)
        self.assertEqual(line.credited_amount, 175600.0)
        self.assertEqual(line.direct_cost, 285780.0)
        self.assertAlmostEqual(line.closing_amount, line.total_cost - 175600.0, places=2)
        calc.action_post()
        # продукція доведена до фактичної собівартості
        self.assertAlmostEqual(self._balance(self.acc_27), line.total_cost, places=2)

    def _closing_27(self):
        """Сума, яку закриття складу провело б по рахунку 27."""
        vals = self.company._action_close_stock_valuation()
        return sum(v.get('debit', 0.0) - v.get('credit', 0.0)
                   for v in vals if v['account_id'] == self.acc_27.id)

    def test_stock_value_matches_produce_account(self):
        """#603: склад оцінює врожай так само, як рахунок 27."""
        receipt = self._harvest()
        self.assertEqual(receipt.move_id.value, 800000.0)
        self.assertAlmostEqual(self.grain.total_value, 800000.0, places=2)
        self.assertAlmostEqual(self.grain.standard_price, 8.0, places=4)
        self.assertAlmostEqual(self._closing_27(), 0.0, places=2)

    def test_planned_cost_adjusts_stock(self):
        """Доведення до фактичної собівартості змінює і вартість на складі."""
        self.company.l10n_ua_agro_valuation_method = 'planned_cost'
        self._work()
        receipt = self._harvest()
        self.assertAlmostEqual(self.grain.total_value, 175600.0, places=2)
        calc = self._calculation()
        line = calc.line_ids.filtered(lambda l: l.planting_id == self.planting)
        calc.action_post()
        self.assertAlmostEqual(receipt.cost_adjustment, line.total_cost - 175600.0, places=2)
        self.assertAlmostEqual(self.grain.total_value, line.total_cost, places=2)
        self.assertAlmostEqual(self._balance(self.acc_27), line.total_cost, places=2)
        self.assertAlmostEqual(self._closing_27(), 0.0, places=2)
        calc.action_cancel()
        self.assertEqual(receipt.cost_adjustment, 0.0)
        self.assertAlmostEqual(self.grain.total_value, 175600.0, places=2)
        self.assertAlmostEqual(self._balance(self.acc_27), 175600.0, places=2)

    def test_standard_price_costing_refused(self):
        self.produce_categ.property_cost_method = 'standard'
        with self.assertRaises(UserError):
            self._harvest()

    def test_real_time_no_double_entry(self):
        """Складська проводка руху з виробничої локації не задвоює Дт 27."""
        self.produce_categ.property_valuation = 'real_time'
        self.grain.property_stock_production.valuation_account_id = self.acc_231
        receipt = self._harvest()
        self.assertFalse(receipt.move_id.account_move_id)
        self.assertEqual(self._balance(self.acc_27), 800000.0)

    def test_missing_fair_value(self):
        self.env['l10n_ua.agro.fair.value'].search([]).unlink()
        with self.assertRaises(UserError):
            self._harvest()
