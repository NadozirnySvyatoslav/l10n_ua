"""Уцінка запасів до чистої вартості реалізації (НП(С)БО 9, п. 24–28) — #518.

Товар з середньозваженою собівартістю: 10 шт по 100 грн надійшло на склад.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestInventoryWritedown(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_946 = acc('946', 'Втрати від знецінення запасів', 'expense')
        cls.acc_719 = acc('719', 'Інші доходи операційної діяльності', 'income_other')
        cls.category = cls.env['product.category'].create({
            'name': 'Товари (уцінка)',
            'property_cost_method': 'average',
            'property_stock_valuation_account_id': cls.acc_281.id,
        })
        cls.product = cls._product('Товар А', cls.category)
        cls._receive(cls.product, 10, 100.0)

    @classmethod
    def _account(cls, code, name, account_type):
        Account = cls.env['account.account']
        return Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1) \
            or Account.create({'code': code, 'name': name, 'account_type': account_type,
                               'company_ids': [(6, 0, cls.company.ids)]})

    @classmethod
    def _product(cls, name, category):
        return cls.env['product.product'].create({
            'name': name, 'type': 'consu', 'is_storable': True, 'categ_id': category.id,
        })

    @classmethod
    def _receive(cls, product, qty, price):
        product.standard_price = price
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        move = cls.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': cls.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'price_unit': price,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()

    @classmethod
    def _deliver(cls, product, qty):
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        move = cls.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': cls.env.ref('stock.stock_location_customers').id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()

    def _writedown(self, nrv, product=None, **vals):
        vals.setdefault('date', fields.Date.today())
        doc = self.env['l10n_ua.inventory.writedown'].create({
            'company_id': self.company.id, **vals})
        doc.action_fill()
        line = doc.line_ids.filtered(lambda l: l.product_id == (product or self.product))
        if nrv is not None:
            line.nrv_unit = nrv
        return doc, line

    def _value(self, product=None):
        return (product or self.product).with_company(self.company).total_value

    # ------------------------------------------------------------------ уцінка

    def test_fill_takes_book_value(self):
        doc, line = self._writedown(None)
        self.assertEqual(line.quantity, 10)
        self.assertAlmostEqual(line.book_value, 1000.0)
        self.assertAlmostEqual(line.book_unit_cost, 100.0)
        self.assertEqual(doc.loss_account_id, self.acc_946)
        self.assertEqual(doc.income_account_id, self.acc_719)
        self.assertEqual(line.valuation_account_id, self.acc_281)

    def test_empty_nrv_is_not_zero(self):
        doc, line = self._writedown(None)
        self.assertFalse(line.writedown_amount)
        doc.action_post()
        self.assertFalse(doc.move_id)
        self.assertAlmostEqual(self._value(), 1000.0)

    def test_writedown_posts_946_and_revalues_stock(self):
        doc, line = self._writedown(70.0)
        self.assertAlmostEqual(line.writedown_amount, 300.0)
        self.assertAlmostEqual(line.new_unit_cost, 70.0)
        doc.action_post()
        self.assertEqual(doc.state, 'posted')
        debit = doc.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_946)
        credit = doc.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_281)
        self.assertAlmostEqual(debit.debit, 300.0)
        self.assertAlmostEqual(credit.credit, 300.0)
        # Складська оцінка рухається разом із Головною книгою.
        self.assertAlmostEqual(self._value(), 700.0)
        self.assertAlmostEqual(self.product.with_company(self.company).standard_price, 70.0)

    def test_nrv_above_cost_without_prior_writedown_does_nothing(self):
        doc, line = self._writedown(130.0)
        self.assertFalse(line.writedown_amount)
        self.assertFalse(line.reversal_amount)

    def test_reversal_limited_to_prior_writedown(self):
        first, _line = self._writedown(70.0)
        first.action_post()
        second, line = self._writedown(90.0)
        self.assertAlmostEqual(line.prior_writedown, 300.0)
        self.assertAlmostEqual(line.reversal_amount, 200.0)
        second.action_post()
        income = second.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_719)
        self.assertAlmostEqual(income.credit, 200.0)
        self.assertAlmostEqual(self._value(), 900.0)
        # ЧВР вище первісної вартості: дохід лише в межах решти уцінки (п. 28).
        third, line = self._writedown(130.0)
        self.assertAlmostEqual(line.prior_writedown, 100.0)
        self.assertAlmostEqual(line.reversal_amount, 100.0)
        third.action_post()
        self.assertAlmostEqual(self._value(), 1000.0)

    def test_exempt_material_is_not_written_down(self):
        doc, line = self._writedown(50.0)
        line.exempt = True
        self.assertFalse(line.writedown_amount)

    def test_cancel_restores_value(self):
        doc, _line = self._writedown(60.0)
        doc.action_post()
        self.assertAlmostEqual(self._value(), 600.0)
        doc.action_cancel()
        self.assertEqual(doc.state, 'cancelled')
        reversal = self.env['account.move'].search([('reversed_entry_id', '=', doc.move_id.id)])
        self.assertEqual(reversal.state, 'posted')
        self.assertAlmostEqual(
            sum(reversal.line_ids.filtered(lambda l: l.account_id == self.acc_946).mapped('credit')),
            400.0)
        self.assertAlmostEqual(self._value(), 1000.0)

    def test_reversal_limited_to_quantity_on_hand(self):
        """Ліміт сторно — уцінка на одиницю × поточний залишок, не вся уцінка.

        10 од. по 100 уцінено до 90 (100 на 946), 9 од. продано; ЧВР решти
        1 од. зросла до 150 → дохід 10 (а не min(60, 100) = 60), ціна 100.
        """
        first, _line = self._writedown(90.0)
        first.action_post()
        # Власний документ у ліміт не входить.
        self.assertFalse(first.line_ids._prior_values(10, 90.0)['prior_writedown'])
        second, line = self._writedown(None, date=fields.Date.add(fields.Date.today(), days=1))
        values = line._prior_values(1, 90.0)
        self.assertAlmostEqual(values['prior_unit_writedown'], 10.0)
        self.assertAlmostEqual(values['prior_cost_cap'], 100.0)
        line.write({'quantity': 1, 'book_value': 90.0, **values})
        line.nrv_unit = 150.0
        self.assertAlmostEqual(line.prior_writedown, 10.0)
        self.assertAlmostEqual(line.reversal_amount, 10.0)
        self.assertAlmostEqual(line.new_unit_cost, 100.0)

    def test_cancel_refused_after_goods_moved(self):
        """Уцінка → продаж частини → скасування заборонено: склад = ГК."""
        doc, _line = self._writedown(80.0)
        doc.action_post()
        self._deliver(self.product, 5)
        with self.assertRaisesRegex(UserError, 'moved'):
            doc.action_cancel()
        self.assertEqual(doc.state, 'posted')

    def test_backdated_writedown_refused_after_moves(self):
        """Уцінка заднім числом, коли після дати вже були рухи товару."""
        doc, _line = self._writedown(None, date=fields.Date.subtract(fields.Date.today(), days=1))
        # Товар надійшов сьогодні; рядок «на вчора» — вручну, щоб була сума уцінки.
        self.env['l10n_ua.inventory.writedown.line'].create({
            'writedown_id': doc.id, 'product_id': self.product.id,
            'quantity': 10, 'book_value': 1000.0, 'nrv_unit': 80.0,
        })
        self.assertAlmostEqual(doc.total_writedown, 200.0)
        with self.assertRaisesRegex(UserError, 'after the document date'):
            doc._check_postable()

    def test_cancel_checks_later_writedown_by_date(self):
        """Пізніша за датою уцінка, створена раніше (менший id), блокує скасування."""
        later, _line = self._writedown(
            90.0, date=fields.Date.add(fields.Date.today(), days=1))
        earlier, _line = self._writedown(80.0)
        self.assertLess(later.id, earlier.id)
        earlier.action_post()
        later.action_post()
        with self.assertRaisesRegex(UserError, 'later write-down'):
            earlier.action_cancel()

    def test_partial_stock_reversal_end_to_end(self):
        """Уцінка → продаж 9 од. → сторно на залишку 1 од.: склад = ГК.

        10 од. по 100 → 90 (100 на 946), продано 9; ЧВР решти зросла до 150 →
        дохід 10 на 719, ціна 100, вартість залишку 100.
        """
        first, _line = self._writedown(90.0)
        first.action_post()
        self.assertAlmostEqual(self._value(), 900.0)
        self._deliver(self.product, 9)
        self.assertAlmostEqual(self._value(), 90.0)
        second, line = self._writedown(150.0)
        self.assertEqual(line.quantity, 1)
        self.assertAlmostEqual(line.prior_writedown, 10.0)
        self.assertAlmostEqual(line.reversal_amount, 10.0)
        second.action_post()
        income = second.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_719)
        self.assertAlmostEqual(income.credit, 10.0)
        self.assertAlmostEqual(self._value(), 100.0)

    def test_cleared_nrv_is_not_zero(self):
        """Очищена у формі ЧВР (клієнт шле 0) — не нуль; уцінка до нуля — лише прапорцем."""
        doc, line = self._writedown(None)
        with Form(doc) as form:
            with form.line_ids.edit(0) as row:
                row.nrv_unit = 80.0
                self.assertTrue(row.nrv_set)
        self.assertTrue(line.nrv_set)
        self.assertAlmostEqual(line.writedown_amount, 200.0)
        # Очищення поля: веб-клієнт шле 0, як і Form.
        with Form(doc) as form:
            with form.line_ids.edit(0) as row:
                row.nrv_unit = 0.0
                self.assertFalse(row.nrv_set)
        self.assertFalse(line.nrv_set)
        self.assertFalse(line.writedown_amount)
        self.assertAlmostEqual(line.new_unit_cost, 100.0)
        # Уцінка до нуля — явно: 0 і прапорець «ЧВР введено».
        with Form(doc) as form:
            with form.line_ids.edit(0) as row:
                row.nrv_set = True
        self.assertTrue(line.nrv_set)
        self.assertAlmostEqual(line.writedown_amount, 1000.0)
        # Програмний запис без прапорця: 0 — «не введено».
        line.nrv_unit = 0.0
        self.assertFalse(line.nrv_set)

    def test_other_company_user_does_not_see_lines(self):
        doc, line = self._writedown(80.0)
        other = self.env['res.company'].create({'name': 'Інша компанія (уцінка)'})
        user = self.env['res.users'].create({
            'name': 'Бухгалтер іншої компанії', 'login': 'writedown_other_company',
            'company_id': other.id, 'company_ids': [(6, 0, other.ids)],
            'group_ids': [(6, 0, self.env.ref('account.group_account_user').ids)],
        })
        Line = self.env['l10n_ua.inventory.writedown.line'].with_user(user)
        Doc = self.env['l10n_ua.inventory.writedown'].with_user(user)
        self.assertFalse(Line.search([('id', '=', line.id)]))
        self.assertFalse(Doc.search([('id', '=', doc.id)]))
        # Свій користувач рядок бачить — правило не ховає все підряд.
        self.assertEqual(self.env['l10n_ua.inventory.writedown.line'].search(
            [('id', '=', line.id)]), line)

    def test_fifo_refused(self):
        fifo = self.env['product.category'].create({
            'name': 'ФІФО', 'property_cost_method': 'fifo',
            'property_stock_valuation_account_id': self.acc_281.id,
        })
        product = self._product('Товар ФІФО', fifo)
        self._receive(product, 5, 40.0)
        doc, _line = self._writedown(30.0, product=product)
        with self.assertRaisesRegex(UserError, 'FIFO'):
            doc.action_post()

    def test_posted_cannot_be_deleted(self):
        doc, _line = self._writedown(80.0)
        doc.action_post()
        with self.assertRaises(UserError):
            doc.unlink()

    def test_stock_closing_does_not_undo_writedown(self):
        """Закриття оцінки запасів Odoo доводить рахунок до складської оцінки;
        уцінка змінює обидві однаково, тож різниця, яку закриття проведе, та сама."""
        def gap():
            stock = self.company.stock_value()
            books = self.company.stock_accounting_value()
            return stock.get(self.acc_281, 0.0) - books.get(self.acc_281, 0.0)

        before = gap()
        doc, _line = self._writedown(75.0)
        doc.action_post()
        self.assertAlmostEqual(gap(), before)
