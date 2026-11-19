"""ОСВ з розгорткою по номенклатурі (#588, п. 3).

Синтетична ОСВ з прапорцем «Розгорнути по номенклатурі»: рахунки з
аналітикою по номенклатурі (``ua_analytics_type`` = product, 20х/22/26/28)
отримують рядок рахунку і рядки-розгортку по кожному товару — сальдо й
обороти в сумі і в кількості (``quantity`` рядків проводок: дебет —
надійшло, кредит — вибуло).
"""

from datetime import date

from odoo.tests import TransactionCase, tagged

MONEY = ('opening_debit', 'opening_credit', 'turnover_debit',
         'turnover_credit', 'closing_debit', 'closing_credit')
QTY = ('opening_qty', 'turnover_qty_in', 'turnover_qty_out', 'closing_qty')


@tagged('post_install', '-at_install')
class TestOsvProductExpand(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'ОСВ номенклатура',
            'code': 'OSVP',
            'type': 'general',
            'company_id': cls.company.id,
        })

        def account(code, name, account_type, analytics='none'):
            return cls.env['account.account'].create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'ua_analytics_type': analytics,
                'company_ids': [(4, cls.company.id)],
            })

        # 281-подібний: товари на складі.
        cls.acc_goods = account('OSVP281', 'ОСВ товари', 'asset_current', 'product')
        cls.acc_settle = account('OSVP631', 'ОСВ постачальники', 'liability_current', 'partner')
        cls.acc_cost = account('OSVP902', 'ОСВ собівартість', 'expense')

        Product = cls.env['product.product']
        cls.prod_a = Product.create({'name': 'ОСВП Товар А'})
        cls.prod_b = Product.create({'name': 'ОСВП Товар Б'})
        cls.supplier = cls.env['res.partner'].create({'name': 'ОСВП Постачальник'})
        cls.buyer = cls.env['res.partner'].create({'name': 'ОСВП Покупець'})

    def _post(self, move_date, debit_acc, credit_acc, amount, qty=0.0,
              debit_product=None, credit_product=None,
              debit_partner=None, credit_partner=None):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id,
                    'product_id': debit_product.id if debit_product else False,
                    'partner_id': debit_partner.id if debit_partner else False,
                    'quantity': qty if debit_product else 0.0,
                    'debit': amount,
                }),
                (0, 0, {
                    'account_id': credit_acc.id,
                    'product_id': credit_product.id if credit_product else False,
                    'partner_id': credit_partner.id if credit_partner else False,
                    'quantity': qty if credit_product else 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _osv(self, products=True, partners=False):
        osv = self.env['l10n_ua.osv'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'osv_type': 'synthetic',
            'expand_partners': partners,
            'expand_products': products,
            'company_id': self.company.id,
        })
        osv.action_compute()
        return osv

    def _summary(self, osv, account):
        return osv.line_ids.filtered(
            lambda l: l.account_id == account and not l.is_detail)

    def _details(self, osv, account):
        return osv.line_ids.filtered(
            lambda l: l.account_id == account and l.is_detail)

    def _assert_vals(self, line, **expected):
        self.assertEqual(len(line), 1)
        for field in MONEY + QTY:
            self.assertAlmostEqual(
                line[field], expected.get(field, 0.0),
                msg=f'{line.account_id.code} {line.product_id.name or "—"}: {field}')

    def _goods_data(self):
        # До періоду: надійшло А 10 шт × 100.
        self._post(date(2024, 12, 20), self.acc_goods, self.acc_settle, 1000.0, 10,
                   debit_product=self.prod_a, credit_partner=self.supplier)
        # У періоді: надійшло Б 5 шт × 40, списано А 4 шт.
        self._post(date(2025, 1, 10), self.acc_goods, self.acc_settle, 200.0, 5,
                   debit_product=self.prod_b, credit_partner=self.supplier)
        self._post(date(2025, 1, 20), self.acc_cost, self.acc_goods, 400.0, 4,
                   credit_product=self.prod_a)

    def test_goods_by_product_amount_and_quantity(self):
        """Критерій 4: по кожному товару сальдо й обороти в сумі і кількості."""
        self._goods_data()
        osv = self._osv()

        details = self._details(osv, self.acc_goods)
        self.assertEqual(details.product_id, self.prod_a | self.prod_b)
        self.assertFalse(details.partner_id)
        self._assert_vals(
            details.filtered(lambda l: l.product_id == self.prod_a),
            opening_debit=1000.0, opening_qty=10.0,
            turnover_credit=400.0, turnover_qty_out=4.0,
            closing_debit=600.0, closing_qty=6.0)
        self._assert_vals(
            details.filtered(lambda l: l.product_id == self.prod_b),
            turnover_debit=200.0, turnover_qty_in=5.0,
            closing_debit=200.0, closing_qty=5.0)

        summary = self._summary(osv, self.acc_goods)
        for field in MONEY + QTY:
            self.assertAlmostEqual(summary[field], sum(details.mapped(field)), msg=field)

        # Сума розгортки = синтетичний рахунок без прапорця.
        plain = self._summary(self._osv(products=False), self.acc_goods)
        for field in MONEY:
            self.assertAlmostEqual(summary[field], plain[field], msg=field)

    def test_without_flag_numbers_unchanged(self):
        """Критерій 5: без прапорця — один рядок, кількості немає."""
        self._goods_data()
        osv = self._osv(products=False)
        self.assertFalse(osv.line_ids.filtered('is_detail'))
        line = self._summary(osv, self.acc_goods)
        self._assert_vals(line, opening_debit=1000.0, turnover_debit=200.0,
                          turnover_credit=400.0, closing_debit=800.0)

    def test_product_flag_does_not_expand_partners(self):
        """Лише номенклатура: рахунки контрагентів — згорнутий рядок."""
        self._goods_data()
        osv = self._osv()
        self.assertFalse(self._details(osv, self.acc_settle))
        self._assert_vals(self._summary(osv, self.acc_settle),
                          opening_credit=1000.0, turnover_credit=200.0,
                          closing_credit=1200.0)

    def test_both_flags(self):
        """Обидва прапорці: 631 — по контрагентах, 281 — по товарах."""
        self._goods_data()
        osv = self._osv(partners=True)
        self.assertEqual(self._details(osv, self.acc_settle).partner_id, self.supplier)
        self.assertEqual(self._details(osv, self.acc_goods).product_id,
                         self.prod_a | self.prod_b)
        self.assertFalse(self._details(osv, self.acc_cost))

    def test_lines_without_product_get_own_row(self):
        """Ручна проводка на 281 без товару — окремий рядок з порожнім товаром."""
        self._goods_data()
        self._post(date(2025, 1, 25), self.acc_goods, self.acc_settle, 50.0,
                   credit_partner=self.supplier)
        details = self._details(self._osv(), self.acc_goods)
        self.assertEqual(len(details), 3)
        self._assert_vals(details.filtered(lambda l: not l.product_id),
                          turnover_debit=50.0, closing_debit=50.0)

    def _post_lines(self, move_date, lines):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [(0, 0, vals) for vals in lines],
        })
        move.action_post()
        return move

    def test_storno_return_and_negative_quantity(self):
        """Кейс 7 Галини (#594): сторно-повернення постачальнику (Дт −100,
        1 шт) і рядок з від'ємною кількістю на кредиті (−1 шт) — обидва
        вибуття; кількість сходиться із сумою."""
        self.company.account_storno = True
        self._goods_data()
        # Повернення постачальнику А 1 шт: сторно Дт 281 −100 / Кт 631 −100.
        storno = self._post_lines(date(2025, 1, 25), [
            {'account_id': self.acc_goods.id, 'product_id': self.prod_a.id,
             'quantity': 1.0, 'debit': -100.0},
            {'account_id': self.acc_settle.id, 'partner_id': self.supplier.id,
             'credit': -100.0},
        ])
        self.assertTrue(storno.line_ids.filtered(
            lambda l: l.account_id == self.acc_goods).is_storno)
        # Рядок рахунку з −1 шт: Кт 281 100, quantity −1.
        self._post_lines(date(2025, 1, 26), [
            {'account_id': self.acc_settle.id, 'partner_id': self.supplier.id,
             'debit': 100.0},
            {'account_id': self.acc_goods.id, 'product_id': self.prod_a.id,
             'quantity': -1.0, 'credit': 100.0},
        ])
        line_a = self._details(self._osv(), self.acc_goods).filtered(
            lambda l: l.product_id == self.prod_a)
        # 10 − 4 (списання) − 1 (сторно-повернення) − 1 (−1 шт) = 4 шт / 400.
        self._assert_vals(
            line_a,
            opening_debit=1000.0, opening_qty=10.0,
            turnover_debit=-100.0, turnover_qty_in=-1.0,
            turnover_credit=500.0, turnover_qty_out=5.0,
            closing_debit=400.0, closing_qty=4.0)

    def test_zero_account_without_analytics_skipped(self):
        """Рахунок без аналітики з протилежними сальдо партнерів, що в сумі 0,
        не дає нульового рядка (як і синтетична ОСВ без прапорців)."""
        self._post(date(2024, 12, 1), self.acc_cost, self.acc_settle, 100.0,
                   debit_partner=self.supplier, credit_partner=self.supplier)
        self._post(date(2024, 12, 2), self.acc_settle, self.acc_cost, 100.0,
                   debit_partner=self.buyer, credit_partner=self.buyer)
        expanded = self._osv(partners=True)
        plain = self._osv(products=False)
        self.assertFalse(self._summary(plain, self.acc_cost))
        self.assertFalse(self._summary(expanded, self.acc_cost))
