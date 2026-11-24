"""Рядки ПН мають відповідати рядкам документа — по складу, базі та ставці."""
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_account_vat')
class TestTaxInvoiceLines(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.l10n_ua_is_vat_payer = True
        cls.customer = cls.env['res.partner'].create({'name': 'Покупець ПН'})
        cls.vat_20 = cls.env['account.tax'].create({
            'name': 'ПДВ 20% (тест)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id,
        })
        cls.vat_20_incl = cls.env['account.tax'].create({
            'name': 'ПДВ 20% у ціні (тест)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include_override': 'tax_included',
            'company_id': cls.env.company.id,
        })
        cls.vat_7 = cls.env['account.tax'].create({
            'name': 'ПДВ 7% (тест)', 'amount': 7.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id,
        })
        cls.vat_20_group = cls.env['account.tax'].create({
            'name': 'ПДВ 20% у групі (тест)', 'amount_type': 'group',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id,
            'children_tax_ids': [(6, 0, cls.vat_20.ids)],
        })
        cls.other_currency = cls.setup_other_currency('EUR')

    def _invoice(self, lines, **move_vals):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_date': '2025-05-05',
            'date': '2025-05-05',
            'invoice_line_ids': [(0, 0, vals) for vals in lines],
            **move_vals,
        })
        move.action_post()
        return move

    def _tax_invoice(self, move):
        move.action_create_tax_invoice()
        return self.env['l10n_ua.tax.invoice'].search([('move_id', '=', move.id)], limit=1)

    def test_lines_are_created_at_all(self):
        """Головна регресія: фільтр display_type лишав ПН геть без рядків."""
        move = self._invoice([
            {'name': 'товар', 'quantity': 10, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
            {'name': 'послуга', 'quantity': 1, 'price_unit': 500.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(len(tax_invoice.line_ids), 2,
                          'ПН має містити стільки ж товарних рядків, скільки документ')
        self.assertGreater(tax_invoice.total_vat, 0.0,
                            'сума ПДВ у ПН не може бути нульовою для оподаткованої операції')

    def test_sections_and_notes_are_skipped(self):
        """Секції та примітки — оформлення документа, у ПН їм місця немає."""
        move = self._invoice([
            {'name': 'Розділ', 'display_type': 'line_section'},
            {'name': 'товар', 'quantity': 2, 'price_unit': 50.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
            {'name': 'Примітка', 'display_type': 'line_note'},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(len(tax_invoice.line_ids), 1)
        self.assertEqual(tax_invoice.line_ids.name, 'товар')

    def test_discount_is_reflected_in_base(self):
        """База ПН має збігатися з базою документа, а не ігнорувати знижку."""
        move = self._invoice([
            {'name': 'товар', 'quantity': 10, 'price_unit': 100.0, 'discount': 10.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
        ])
        invoice_line = move.invoice_line_ids

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(invoice_line.price_subtotal, 900.0)
        self.assertAlmostEqual(tax_invoice.line_ids.base_amount, 900.0, places=2,
                                msg='знижка на рядку загубилась у ПН')
        self.assertAlmostEqual(tax_invoice.line_ids.vat_amount, 180.0, places=2)

    def test_price_included_tax_gives_net_base(self):
        """Для ціни з ПДВ база в ПН — без податку, а не разом із ним."""
        move = self._invoice([
            {'name': 'товар', 'quantity': 1, 'price_unit': 120.0,
             'tax_ids': [(6, 0, self.vat_20_incl.ids)]},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertAlmostEqual(tax_invoice.line_ids.base_amount, 100.0, places=2)
        self.assertAlmostEqual(tax_invoice.line_ids.vat_amount, 20.0, places=2)

    def test_rate_comes_from_the_line_tax(self):
        move = self._invoice([
            {'name': 'ліки', 'quantity': 1, 'price_unit': 200.0,
             'tax_ids': [(6, 0, self.vat_7.ids)]},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(tax_invoice.line_ids.vat_rate, '7')

    def test_line_without_vat_is_not_taxed_at_twenty(self):
        """Рядок без ПДВ не має ставати оподаткованим за 20% через дефолт."""
        move = self._invoice([
            {'name': 'звільнена операція', 'quantity': 1, 'price_unit': 300.0,
             'tax_ids': []},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(tax_invoice.line_ids.vat_rate, 'exempt')
        self.assertEqual(tax_invoice.line_ids.vat_amount, 0.0)

    def test_mixed_rates_keep_their_own_lines(self):
        """Кожен рядок несе свою ставку, а не ставку сусіда."""
        move = self._invoice([
            {'name': 'товар 20', 'quantity': 1, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
            {'name': 'ліки 7', 'quantity': 1, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_7.ids)]},
            {'name': 'без ПДВ', 'quantity': 1, 'price_unit': 100.0, 'tax_ids': []},
        ])

        tax_invoice = self._tax_invoice(move)
        by_name = {line.name: line for line in tax_invoice.line_ids}

        self.assertEqual(by_name['товар 20'].vat_rate, '20')
        self.assertEqual(by_name['ліки 7'].vat_rate, '7')
        self.assertEqual(by_name['без ПДВ'].vat_rate, 'exempt')
        self.assertAlmostEqual(tax_invoice.total_vat, 27.0, places=2)

    def test_grouped_tax_is_not_mistaken_for_exempt(self):
        """ПДВ у складі групи податків — це все одно ПДВ."""
        move = self._invoice([
            {'name': 'товар', 'quantity': 1, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_20_group.ids)]},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(tax_invoice.line_ids.vat_rate, '20')
        self.assertAlmostEqual(tax_invoice.line_ids.vat_amount, 20.0, places=2)

    def test_amounts_are_converted_to_company_currency(self):
        """ПН завжди у гривні, навіть якщо документ — у валюті."""
        move = self._invoice(
            [{'name': 'товар', 'quantity': 2, 'price_unit': 500.0,
              'tax_ids': [(6, 0, self.vat_20.ids)]}],
            currency_id=self.other_currency.id,
        )
        invoice_line = move.invoice_line_ids
        # Еталон рахуємо перерахунком курсу — незалежно від того, що код
        # бере суму з проводки, і без прив'язки до курсу тестової фікстури.
        expected_base = self.other_currency._convert(
            invoice_line.price_subtotal, self.env.company.currency_id,
            self.env.company, move.invoice_date)

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(tax_invoice.currency_id, self.env.company.currency_id)
        self.assertNotEqual(expected_base, invoice_line.price_subtotal,
                            'фікстура має давати курс, відмінний від 1:1')
        self.assertAlmostEqual(tax_invoice.line_ids.base_amount, expected_base, places=2,
                               msg='база ПН лишилась у валюті документа')

    def test_credit_note_reduces_liability(self):
        """РК має зменшувати зобов'язання й посилатися на оригінальну ПН.

        Доти цикл не виконувався й РК виходив порожній, тож знак ніде не
        проявлявся; тепер порожня гілка стала документом.
        """
        move = self._invoice([
            {'name': 'товар', 'quantity': 2, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
        ])
        original = self._tax_invoice(move)

        refund = move._reverse_moves([{
            'invoice_date': '2025-05-10',
            'date': '2025-05-10',
            'ref': 'повернення товару',
        }])
        refund.action_post()
        correction = self._tax_invoice(refund)

        self.assertEqual(correction.doc_type, 'rk')
        self.assertEqual(correction.line_ids.quantity, -2.0)
        self.assertAlmostEqual(correction.line_ids.price_unit, 100.0, places=2,
                               msg='ціна в РК не змінюється — змінюється кількість')
        self.assertAlmostEqual(correction.total_vat, -40.0, places=2,
                               msg='РК зменшує зобов\'язання, а не збільшує')
        self.assertEqual(correction.original_invoice_id, original)
        self.assertEqual(correction.reason, 'повернення товару')

    def test_total_vat_matches_the_document(self):
        """Сума ПДВ у ПН має збігатися з податком документа.

        Кількість 3 і знижка дають базу 379.99, що не ділиться на копійки —
        саме тут округлення ціни до двох знаків давало 126.66 × 3 = 379.98.
        """
        move = self._invoice([
            {'name': 'товар', 'quantity': 3, 'price_unit': 133.33, 'discount': 5.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]},
        ])

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(move.invoice_line_ids.price_subtotal, 379.99)
        self.assertEqual(tax_invoice.line_ids.base_amount, 379.99)
        self.assertEqual(tax_invoice.total_vat, move.amount_tax)

    # --- #599: ПДВ ПН = ПДВ рахунку до копійки -------------------------------

    def _assert_vat_matches_move(self, move, tax_invoice):
        self.assertAlmostEqual(tax_invoice.total_base, abs(move.amount_untaxed_signed), places=2,
                               msg='база ПН має дорівнювати базі документа')
        self.assertAlmostEqual(tax_invoice.total_vat, abs(move.amount_tax_signed), places=2,
                               msg='ПДВ ПН має дорівнювати ПДВ документа до копійки')
        rates = {'20': 0.20, '7': 0.07, '14': 0.14}
        for line in tax_invoice.line_ids:
            expected = line.base_amount * rates.get(line.vat_rate, 0.0)
            self.assertLessEqual(abs(line.vat_amount - expected), 0.0100001,
                                 'різниця округлення на рядку — не більше копійки')

    def test_599a_per_line_price_included(self):
        """(а) «по рядку», ціни з ПДВ 7,77 і 1,05: ПН давала 1,46 замість 1,48."""
        self.env.company.tax_calculation_rounding_method = 'round_per_line'
        move = self._invoice([
            {'name': 'товар 1', 'quantity': 1, 'price_unit': 7.77,
             'tax_ids': [(6, 0, self.vat_20_incl.ids)]},
            {'name': 'товар 2', 'quantity': 1, 'price_unit': 1.05,
             'tax_ids': [(6, 0, self.vat_20_incl.ids)]},
        ])

        self._assert_vat_matches_move(move, self._tax_invoice(move))

    def _three_small_lines(self):
        return [{'name': 'товар %s' % i, 'quantity': 1, 'price_unit': 0.33,
                 'tax_ids': [(6, 0, self.vat_20.ids)]} for i in range(3)]

    def test_599b_global_three_small_lines(self):
        """(б) «глобально», 3 × 0,33 без ПДВ: рахунок 0,20, ПН давала 0,21."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        move = self._invoice(self._three_small_lines())

        tax_invoice = self._tax_invoice(move)

        self.assertAlmostEqual(move.amount_tax, 0.20, places=2)
        self._assert_vat_matches_move(move, tax_invoice)

    def test_599g_global_price_included(self):
        """(г) «глобально», 7,77 з ПДВ: рахунок 1,30, ПН давала 1,29."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        move = self._invoice([
            {'name': 'товар', 'quantity': 1, 'price_unit': 7.77,
             'tax_ids': [(6, 0, self.vat_20_incl.ids)]},
        ])

        self._assert_vat_matches_move(move, self._tax_invoice(move))

    def test_599_credit_note_keeps_document_vat(self):
        """РК на рахунок (б): ПДВ РК = −ПДВ документа, без копійчаного зсуву."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        move = self._invoice(self._three_small_lines())
        self._tax_invoice(move)
        refund = move._reverse_moves([{'invoice_date': '2025-05-10', 'date': '2025-05-10'}])
        refund.action_post()

        correction = self._tax_invoice(refund)

        self.assertAlmostEqual(correction.total_vat, -refund.amount_tax, places=2)

    def test_599_manual_line_still_computes_vat(self):
        """Ручний рядок ПН без рахунку рахує ПДВ від бази, як і раніше."""
        tax_invoice = self.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'issued', 'number': 'РУЧН-599', 'partner_id': self.customer.id,
            'company_id': self.env.company.id, 'date': '2025-05-05',
            'line_ids': [(0, 0, {'name': 'ручний', 'quantity': 1,
                                 'price_unit': 100.0, 'vat_rate': '20'})],
        })
        self.assertAlmostEqual(tax_invoice.line_ids.vat_amount, 20.0, places=2)
        tax_invoice.line_ids.price_unit = 50.0
        self.assertAlmostEqual(tax_invoice.line_ids.vat_amount, 10.0, places=2)

    # --- #599, зауваження BA/pr-review: межа розподілу і касовий метод -------

    def _has_vat_warning(self, tax_invoice):
        return bool(tax_invoice.message_ids.filtered(
            lambda m: 'не відповідає рядкам' in (m.body or '')))

    def _bump_move_vat(self, move, delta):
        """Ручна правка ПДВ у рахунку: tax-рядок і дебіторка на ``delta``."""
        move.button_draft()
        ctx = dict(check_move_validity=False, skip_invoice_sync=True)
        tax_line = move.line_ids.filtered('tax_line_id')
        receivable = move.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        tax_line.with_context(**ctx).write({
            'balance': tax_line.balance - delta,
            'amount_currency': tax_line.amount_currency - delta,
        })
        receivable.with_context(**ctx).write({
            'balance': receivable.balance + delta,
            'amount_currency': receivable.amount_currency + delta,
        })
        move.action_post()

    def test_599_manual_vat_edit_is_not_spread(self):
        """ПДВ рахунку правлено на 1,00: різницю не розкидаємо по рядках, а
        лишаємо база × ставка і пишемо попередження в ПН (З1 BA)."""
        move = self._invoice([
            {'name': 'товар %s' % i, 'quantity': 1, 'price_unit': 100.0,
             'tax_ids': [(6, 0, self.vat_20.ids)]} for i in range(3)])
        self._bump_move_vat(move, 1.0)
        self.assertAlmostEqual(abs(move.amount_tax_signed), 61.0, places=2)

        tax_invoice = self._tax_invoice(move)

        self.assertEqual(tax_invoice.line_ids.mapped('vat_amount'), [20.0, 20.0, 20.0],
                         'ручна різниця не має ховатися в рядках ПН')
        self.assertTrue(self._has_vat_warning(tax_invoice),
                        'ПН має містити попередження про розбіжність ПДВ')

    def test_599_rounding_diff_is_spread_without_warning(self):
        """Звичайна копійка округлення (3 × 0,33) розкладається без попередження."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        move = self._invoice(self._three_small_lines())

        tax_invoice = self._tax_invoice(move)

        self._assert_vat_matches_move(move, tax_invoice)
        self.assertFalse(self._has_vat_warning(tax_invoice))

    def _pay(self, move, payment_date, amount):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids,
        ).create({'payment_date': payment_date, 'amount': amount})
        return wizard._create_payments()

    def test_599_cash_method_partial_payments_sum_to_move_vat(self):
        """Касовий метод, 3 × 0,33 «глобально», дві часткові оплати: сума ПДВ
        усіх ПН = ПДВ рахунку, сума баз = база рахунку (критерій 6 BA)."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        self.customer.with_company(self.env.company).l10n_ua_vat_cash_method = True
        move = self._invoice(self._three_small_lines())
        self.assertAlmostEqual(move.amount_total, 1.19, places=2)

        self._pay(move, '2025-05-10', 0.50)
        self._pay(move, '2025-05-20', move.amount_residual)
        move.action_create_tax_invoice()
        tax_invoices = self.env['l10n_ua.tax.invoice'].search([('move_id', '=', move.id)])

        self.assertEqual(len(tax_invoices), 2, 'по ПН на кожне надходження')
        self.assertAlmostEqual(sum(tax_invoices.mapped('total_vat')),
                               abs(move.amount_tax_signed), places=2)
        self.assertAlmostEqual(sum(tax_invoices.mapped('total_base')),
                               abs(move.amount_untaxed_signed), places=2)
        for tax_invoice in tax_invoices:
            self.assertFalse(self._has_vat_warning(tax_invoice))

    def test_599_resave_keeps_vat(self):
        """З2/критерій 8: збереження форми ПН з рахунку без змін не
        перераховує підігнаний ПДВ рядка."""
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        move = self._invoice(self._three_small_lines())
        tax_invoice = self._tax_invoice(move)
        before = tax_invoice.line_ids.mapped('vat_amount')

        Form(tax_invoice).save()
        tax_invoice.invalidate_recordset()

        self.assertEqual(tax_invoice.line_ids.mapped('vat_amount'), before)
        self.assertAlmostEqual(tax_invoice.total_vat, move.amount_tax, places=2)
