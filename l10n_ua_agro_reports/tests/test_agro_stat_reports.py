from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ua_agro_operations.tests.common import AgroOperationsTestCase


@tagged('post_install', '-at_install')
class TestAgroStatReports(AgroOperationsTestCase):

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
        cls.seed.l10n_ua_agro_material_type = 'seed'
        cls.fertilizer.l10n_ua_agro_material_type = 'fertilizer'
        categ = cls.env['product.category'].create({'name': 'Сільгосппродукція (статзвіт)'})
        categ.property_cost_method = 'average'
        cls.grain = cls.env['product.product'].create({
            'name': 'Пшениця (статзвіт)', 'is_storable': True, 'categ_id': categ.id,
            'uom_id': cls.env.ref('uom.product_uom_kgm').id})
        cls.wheat.product_id = cls.grain
        cls.wheat.write({'base_moisture': 14.0, 'base_impurity': 1.0})
        cls.env['l10n_ua.agro.fair.value'].create({
            'product_id': cls.grain.id, 'date': date(2097, 7, 1), 'price': 8.0})
        cls.card.planned_yield = 50.0
        cls.season_next = cls.env['l10n_ua.agro.season'].create({
            'year': 2098, 'date_start': date(2097, 8, 1), 'date_end': date(2098, 12, 31)})
        cls.field2 = cls.env['l10n_ua.agro.field'].create({'name': 'Біля лісу', 'code': 'T-02', 'area': 50.0})
        cls.planting_next = cls.env['l10n_ua.agro.planting'].create({
            'field_id': cls.field2.id, 'season_id': cls.season_next.id, 'crop_id': cls.wheat.id, 'area': 50.0})
        cls.meadow = cls.env['l10n_ua.agro.field'].create(
            {'name': 'Луки', 'code': 'T-03', 'area': 12.5, 'land_type': 'hayfield'})

    def _report(self, form, year=2097):
        report = self.env['l10n_ua.agro.stat.report'].create({'form': form, 'year': year})
        report.action_compute()
        return report

    def _harvest(self):
        receipt = self.env['l10n_ua.agro.harvest.receipt'].create({
            'date': datetime(2097, 7, 20, 10), 'planting_id': self.planting.id,
            'gross_weight': 114000, 'tare_weight': 14000, 'moisture': 14.0, 'impurity': 1.0,
            'location_dest_id': self.warehouse.lot_stock_id.id})
        receipt.action_done()
        return receipt

    def test_crop_codes_filled(self):
        self.assertEqual(self.wheat.l10n_ua_stat_code, '0070')
        self.assertEqual(self.env.ref('l10n_ua_agro_base.crop_pumpkin_seed').l10n_ua_stat_code, '0597')

    def test_4sg_sown_areas_and_land(self):
        report = self._report('4sg')
        self.assertEqual(report.name, '4-сг під урожай 2097 року')
        self.assertEqual(report.date_deadline, date(2097, 6, 2))
        self.assertEqual(report.get_value('I', '0070'), 100.0)
        fields = self.env['l10n_ua.agro.field'].search([('company_id', '=', self.company.id)])
        arable = sum(fields.filtered(lambda f: f.land_type in ('arable', 'fallow')).mapped('area'))
        hay = sum(fields.filtered(lambda f: f.land_type == 'hayfield').mapped('area'))
        self.assertAlmostEqual(report.get_value('II', '10100'), arable, places=2)
        self.assertAlmostEqual(report.get_value('II', '10200'), hay, places=2)
        self.assertAlmostEqual(report.get_value('II', '10000'), sum(
            report.get_value('II', code) for code in ('10100', '10200', '10300', '10400')), places=2)
        organic = report._line('II', '10000', '2')
        self.assertFalse(organic.is_auto)
        # ручне перекриття переживає перерахунок і входить у підсумок
        pasture = report._line('II', '10300')
        pasture.write({'is_manual': True, 'manual_value': 7.25})
        report.action_compute()
        self.assertEqual(report.get_value('II', '10300'), 7.25)
        self.assertAlmostEqual(report.get_value('II', '10000'),
                               report.get_value('II', '10100') + report.get_value('II', '10200') + 7.25
                               + report.get_value('II', '10400'), places=2)

    def test_29sg_harvest_and_winter_sowing(self):
        self._harvest()
        report = self._report('29sg')
        self.assertEqual(report.date_deadline, date(2098, 1, 11))
        self.assertEqual(report.get_value('I', '0070', '1'), 100.0)
        self.assertEqual(report.get_value('I', '0070', '2'), 1000.0)            # 100 т = 1000 ц
        self.assertFalse(report._line('I', '0070', '3').is_auto)               # политі — вручну
        self.assertEqual(report.get_value('VI', '6200'), 50.0)                 # озима пшениця під 2098
        self.assertTrue(report._line('VII', '7100').is_manual)
        self.assertFalse(report.warning)

    def test_crop_without_code_is_reported(self):
        self.wheat.l10n_ua_stat_code = False
        report = self._report('4sg')
        self.assertIn(self.wheat.name, report.warning)
        self.assertFalse(report._line('I', '0070'))

    def _costs(self):
        sow = self._order(self.op_sow, date=date(2096, 9, 25))
        sow.action_load_norms()
        sow.action_done()                     # насіння 264 000 + пальне 21 780
        fert = self._order(self.op_fert, area=20.0, date=date(2097, 10, 1), planting_id=self.planting_next.id)
        fert.action_load_norms()
        fert.material_ids = [(0, 0, {'product_id': self.fertilizer.id, 'quantity': 3000.0})]
        fert.action_done()                    # добрива 75 000 + пальне 3 630 (озимі 2098)
        for debit, amount in ((self.acc_231, 50000.0), (self.acc_91, 20000.0)):
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': self.journal.id, 'date': date(2097, 6, 30),
                'line_ids': [(0, 0, {'account_id': debit.id, 'debit': amount}),
                             (0, 0, {'account_id': self.acc_685.id, 'credit': amount})]})
            move.action_post()
        self._harvest()
        calc = self.env['l10n_ua.agro.cost.calculation'].create({'season_id': self.season.id})
        calc.action_compute()
        calc.action_post()
        return calc

    def test_50sg_cost_structure_and_expenses(self):
        calc = self._costs()
        line = calc.line_ids.filtered(lambda l: l.planting_id == self.planting)
        report = self._report('50sg')
        self.assertEqual(report.date_deadline, date(2098, 2, 28))
        for row in ('1101', '1102', '1103'):
            self.assertEqual(report.get_value('I', row, '3'), 264.0)          # тис.грн
            self.assertEqual(report.get_value('I', row, '5'), 21.8)
            self.assertAlmostEqual(report.get_value('I', row, '12'),
                                   round((line.allocated_cost + line.overhead_cost) / 1000.0, 1), places=1)
            self.assertAlmostEqual(report.get_value('I', row, '1'), round(line.total_cost / 1000.0, 1),
                                   delta=0.11)
            self.assertAlmostEqual(report.get_value('I', row, '2'), 285.8, places=1)
        # витрати календарного 2097 року: лише наряд жовтня, оренда й 91
        self.assertEqual(report.get_value('II', '2002'), 0.0)
        self.assertEqual(report.get_value('II', '2006'), 75.0)
        self.assertEqual(report.get_value('II', '2007'), 3.6)
        self.assertEqual(report.get_value('II', '2001'), 78.6)
        self.assertEqual(report.get_value('II', '2014'), 50.0)
        self.assertEqual(report.get_value('II', '2012'), 50.0)
        self.assertEqual(report.get_value('II', '2017'), 20.0)
        self.assertTrue(report._line('II', '2008').is_manual)

    def test_50sg_stock_movement(self):
        self._harvest().move_id.write({'date': datetime(2097, 7, 20, 10)})
        processor = self.env['res.partner'].create(
            {'name': 'Олійний завод', 'is_company': True, 'l10n_ua_agro_processor': True})
        stock = self.warehouse.lot_stock_id
        picking = self.env['stock.picking'].create({
            'partner_id': processor.id, 'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': stock.id, 'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'move_ids': [(0, 0, {'product_id': self.grain.id, 'product_uom_qty': 30000.0,
                                 'product_uom': self.grain.uom_id.id, 'location_id': stock.id,
                                 'location_dest_id': self.env.ref('stock.stock_location_customers').id})]})
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.quantity = 30000.0
        picking.button_validate()
        loss = self.env['stock.location'].search([('usage', '=', 'inventory'), ('company_id', 'in', (self.company.id, False))], limit=1)
        move = self.env['stock.move'].create({
            'product_id': self.grain.id, 'product_uom_qty': 1000.0, 'product_uom': self.grain.uom_id.id,
            'location_id': stock.id, 'location_dest_id': loss.id, 'company_id': self.company.id})
        move._action_confirm()
        move._action_assign()
        move.quantity = 1000.0
        move.picked = True
        move._action_done()
        (picking.move_ids | move).write({'date': datetime(2097, 11, 5, 12)})
        report = self._report('50sg')
        for row in ('3001', '3002'):
            self.assertEqual(report.get_value('III', row, '2'), 1000.0)
            self.assertEqual(report.get_value('III', row, '3'), 0.0)
            self.assertEqual(report.get_value('III', row, '4'), 310.0)
            self.assertEqual(report.get_value('III', row, '5'), 300.0)
            self.assertEqual(report.get_value('III', row, '11'), 10.0)
        # наступного року — це запас на початок
        report_next = self._report('50sg', year=2098)
        self.assertEqual(report_next.get_value('III', '3002', '1'), 690.0)

    def test_done_report_is_locked(self):
        report = self._report('29sg')
        report.action_done()
        with self.assertRaises(UserError):
            report.action_compute()
        with self.assertRaises(UserError):
            report.line_ids[:1].write({'is_manual': True, 'manual_value': 1.0})
        report.action_draft()
        self.assertTrue(report.action_print())
        html, _type = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_agro_reports.report_agro_stat', report.ids)
        self.assertIn('ЗВІТ ПРО ПЛОЩІ ТА ВАЛОВІ ЗБОРИ', html.decode())
        self.assertIn('Наказ Держстату', html.decode())
        self.assertEqual(report.action_export_xlsx()['type'], 'ir.actions.act_url')
