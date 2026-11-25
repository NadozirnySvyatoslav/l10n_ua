"""Дата ПН: перша подія проти касового методу (п. 187.10 ПКУ)."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_account_vat')
class TestVatCashMethod(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Покупець (перша подія)'})
        cls.customer_cash = cls.env['res.partner'].create({'name': 'Покупець (касовий)'})
        cls.customer_cash.with_company(cls.env.company).l10n_ua_vat_cash_method = True
        cls.other_currency = cls.setup_other_currency('EUR')

    def _invoice(self, partner, invoice_date):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': invoice_date,
            'date': invoice_date,
            'invoice_line_ids': [(0, 0, {
                'name': 'послуга',
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [],
            })],
        })
        move.action_post()
        return move

    def _pay(self, move, payment_date, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids
        ).create({
            'payment_date': payment_date,
            'amount': amount if amount is not None else move.amount_total,
        })
        return wizard._create_payments()

    # ------------------------------------------------------------ перша подія

    def test_first_event_uses_invoice_date_when_unpaid(self):
        """Без оплати перша подія — відвантаження, тобто дата документа."""
        move = self._invoice(self.customer, '2025-03-10')

        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-03-10'))

    def test_first_event_uses_payment_date_on_prepayment(self):
        """Передоплата — раніша подія, отже ПН за датою грошей."""
        move = self._invoice(self.customer, '2025-03-10')
        self._pay(move, '2025-03-04')

        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-03-04'))

    def test_first_event_keeps_invoice_date_on_postpayment(self):
        """Післяоплата пізніша за відвантаження і дату ПН не зсуває."""
        move = self._invoice(self.customer, '2025-03-10')
        self._pay(move, '2025-04-02')

        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-03-10'))

    def test_first_event_refuses_on_partial_prepayment(self):
        """Часткова передоплата — це дві ПН: на аванс і на відвантаження.

        Без перевірки вийшла б одна ПН на всю тисячу датою авансу: завищене
        зобов'язання в березні й нуль на дату відвантаження. Поділ — #255.
        """
        move = self._invoice(self.customer, '2025-03-10')
        self._pay(move, '2025-03-04', amount=300.0)

        with self.assertRaises(UserError):
            move._l10n_ua_tax_invoice_date()

    def test_first_event_ignores_partial_postpayment(self):
        """Недоплата після відвантаження нічого не зсуває — ПН на дату документа."""
        move = self._invoice(self.customer, '2025-03-10')
        self._pay(move, '2025-04-02', amount=300.0)

        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-03-10'))

    def test_cash_method_reads_flag_from_commercial_partner(self):
        """Режим оподаткування — властивість юрособи, а не її контактів."""
        contact = self.env['res.partner'].create({
            'name': 'Бухгалтерія', 'type': 'invoice',
            'parent_id': self.customer_cash.id,
        })
        move = self._invoice(contact, '2025-03-10')

        self.assertFalse(contact.with_company(self.env.company).l10n_ua_vat_cash_method,
                         'на самому контакті прапорця немає — на це й тест')
        self.assertEqual(move._l10n_ua_tax_invoice_rule(), 'cash')

        self._pay(move, '2025-04-02')
        move.action_create_tax_invoice()

        # Стороною операції в ПН має бути юрособа: ІПН для ЄРПН належить їй,
        # а не контакту, на який виставлено рахунок.
        self.assertEqual(move.tax_invoice_ids.partner_id, self.customer_cash)

    # --------------------------------------------------------- касовий метод

    def test_cash_method_uses_payment_date(self):
        """За касовим методом дата ПН — дата руху коштів, а не документа."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02')

        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-04-02'))

    def test_cash_method_refuses_while_unpaid(self):
        """Поки грошей немає, зобовʼязання не виникло — ПН складати нема на що."""
        move = self._invoice(self.customer_cash, '2025-03-10')

        with self.assertRaises(UserError):
            move._l10n_ua_tax_invoice_date()

    def test_cash_method_partial_payment_gives_pn_on_paid_amount(self):
        """Часткова оплата: ПН на суму надходження, а не документа (п. 187.10)."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02', amount=400.0)

        move.action_create_tax_invoice()
        pn = move.tax_invoice_ids

        self.assertEqual(len(pn), 1)
        self.assertEqual(pn.date, fields.Date.to_date('2025-04-02'))
        self.assertAlmostEqual(pn.total_base, 400.0)
        # Ціна лишається фактичною ціною постачання, зменшується обсяг.
        self.assertAlmostEqual(pn.line_ids.price_unit, 1000.0)
        self.assertAlmostEqual(pn.line_ids.quantity, 0.4)

    def test_cash_method_pn_per_settlement(self):
        """Два надходження — дві ПН, кожна своєю датою і на свою суму.

        Сценарій #255: рахунок 1000 грн, оплати 400 грн 02.04 і 600 грн 06.05.
        Раніше виходила одна ПН на 1000 грн від 02.04 — завищене зобов'язання
        у квітні й нуль у травні.
        """
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02', amount=400.0)
        self._pay(move, '2025-05-06', amount=600.0)

        action = move.action_create_tax_invoice()
        pns = move.tax_invoice_ids.sorted('date')

        self.assertEqual(move.tax_invoice_count, 2)
        self.assertEqual(pns.mapped('date'), [fields.Date.to_date('2025-04-02'),
                                              fields.Date.to_date('2025-05-06')])
        self.assertEqual(pns.mapped('total_base'), [400.0, 600.0])
        self.assertEqual(set(pns.mapped('vat_method')), {'cash'})
        self.assertEqual(len(pns.partial_reconcile_id), 2,
                         'кожна ПН прив\'язана до свого погашення')
        self.assertTrue(all(pns.mapped('payment_move_id')))
        self.assertEqual(action['domain'], [('id', 'in', pns.ids)],
                         'кілька ПН відкриваються списком')
        self.assertEqual(move.action_view_tax_invoices()['domain'],
                         [('move_id', '=', move.id)])

    def test_cash_method_repeated_call_adds_only_missing(self):
        """Повторне «Створити ПН» складає ПН лише на нові надходження."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02', amount=400.0)
        move.action_create_tax_invoice()
        first = move.tax_invoice_ids

        self._pay(move, '2025-05-06', amount=600.0)
        move.action_create_tax_invoice()

        self.assertEqual(move.tax_invoice_count, 2)
        second = move.tax_invoice_ids - first
        self.assertEqual(second.date, fields.Date.to_date('2025-05-06'))
        self.assertAlmostEqual(second.total_base, 600.0)

        with self.assertRaises(UserError):
            move.action_create_tax_invoice()
        self.assertEqual(move.tax_invoice_count, 2, 'дубля немає')

    def test_cash_method_cancelled_pn_is_replaced(self):
        """Скасована ПН надходження не покриває — на нього складається нова."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02')
        move.action_create_tax_invoice()
        move.tax_invoice_ids.action_cancel()

        move.action_create_tax_invoice()

        self.assertEqual(move.tax_invoice_count, 2)
        self.assertEqual(len(move.tax_invoice_ids.filtered(
            lambda t: t.state != 'cancelled')), 1)

    def test_cash_method_multiline_rounding(self):
        """Копійки розкладаються так, що й ПН, і рядки сходяться з документом.

        Три рядки по 100 грн і три оплати по 100: третина рядка — 33,333…
        Кожна ПН має бути рівно на 100,00, а сума кожного рядка по трьох ПН —
        рівно 100,00, без копійки «в повітрі».
        """
        tax = self.env['account.tax'].create({
            'name': 'ПДВ 20% (тест)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include_override': 'tax_excluded',
        })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_cash.id,
            'invoice_date': '2025-03-10',
            'date': '2025-03-10',
            'invoice_line_ids': [(0, 0, {
                'name': f'послуга {i}', 'quantity': 1, 'price_unit': 100.0,
                'tax_ids': [(6, 0, tax.ids)],
            }) for i in range(3)],
        })
        move.action_post()
        self.assertAlmostEqual(move.amount_total, 360.0)
        for day in ('2025-04-02', '2025-04-15', '2025-05-06'):
            self._pay(move, day, amount=120.0)

        move.action_create_tax_invoice()
        pns = move.tax_invoice_ids.sorted('date')

        self.assertEqual(len(pns), 3)
        for pn in pns:
            self.assertAlmostEqual(pn.total_base, 100.0, places=2)
            # ПДВ рядка ПН рахується від його бази й округлюється по рядку,
            # тож на «розрізаних» копійках підсумок може відійти на копійку.
            self.assertAlmostEqual(pn.total_vat, 20.0, delta=0.015)
            self.assertEqual(set(pn.line_ids.mapped('vat_rate')), {'20'})
        for name in ('послуга 0', 'послуга 1', 'послуга 2'):
            lines = pns.line_ids.filtered(lambda l: l.name == name)
            self.assertAlmostEqual(sum(lines.mapped('base_amount')), 100.0, places=2)
            self.assertAlmostEqual(sum(lines.mapped('quantity')), 1.0, places=6)
        self.assertEqual(pns[0].line_ids.mapped('base_amount'), [33.33, 33.33, 33.34])

    def test_cash_method_unreconciled_payment_blocks_generation(self):
        """ПН, що втратила погашення, не дає мовчки скласти дубль.

        Оплату розʼєднали з рахунком і зіставили знову — без перевірки на те
        саме надходження вийшла б друга ПН, тобто подвійне зобов'язання.
        """
        move = self._invoice(self.customer_cash, '2025-03-10')
        payment = self._pay(move, '2025-04-02')
        move.action_create_tax_invoice()
        pn = move.tax_invoice_ids

        receivable = move.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        receivable.remove_move_reconcile()
        self.assertFalse(pn.partial_reconcile_id)
        self.assertEqual(pn.payment_move_id, payment.move_id,
                         'видно, яке надходження ПН описувала')

        (receivable | payment.move_id.line_ids.filtered(
            lambda l: l.account_id == receivable.account_id)).reconcile()
        with self.assertRaises(UserError):
            move.action_create_tax_invoice()
        self.assertEqual(move.tax_invoice_count, 1)

        # Людина вирішила, що стара ПН зайва, — тепер нова складається.
        pn.action_cancel()
        move.action_create_tax_invoice()
        self.assertEqual(len(move.tax_invoice_ids.filtered(
            lambda t: t.state != 'cancelled')), 1)

    def test_settlement_without_payment_object_counts(self):
        """Залік кредит-ноти — теж погашення, хоч account.payment там немає."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        credit_note = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.customer_cash.id,
            'invoice_date': '2025-04-02',
            'date': '2025-04-02',
            'invoice_line_ids': [(0, 0, {
                'name': 'залік', 'quantity': 1, 'price_unit': 1000.0, 'tax_ids': []})],
        })
        credit_note.action_post()
        receivable = (move.line_ids | credit_note.line_ids).filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        receivable.reconcile()

        self.assertFalse(move.matched_payment_ids,
                         'у цьому сценарії платіжного документа немає — на це й тест')
        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-04-02'))

    def test_exchange_difference_is_not_a_second_settlement(self):
        """Курсова різниця — не друге надходження, а технічна проводка."""
        self.env['res.currency.rate'].create({
            'name': '2025-04-02',
            'rate': 4.0,
            'currency_id': self.other_currency.id,
            'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_cash.id,
            'invoice_date': '2025-03-10',
            'date': '2025-03-10',
            'currency_id': self.other_currency.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'послуга', 'quantity': 1, 'price_unit': 1000.0, 'tax_ids': []})],
        })
        move.action_post()
        self._pay(move, '2025-04-02')

        # Курс на дату оплати інший, тож Odoo проводить курсову різницю
        # окремим документом на тому ж рахунку розрахунків.
        self.assertTrue(move.currency_id.is_zero(move.amount_residual))
        self.assertEqual(move._l10n_ua_settlement_dates(),
                         [fields.Date.to_date('2025-04-02')],
                         'курсова різниця не має рахуватись окремим надходженням')
        self.assertEqual(move._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-04-02'))

    # -------------------------------------------------- чужі й коригуючі ПН

    def test_vendor_bill_keeps_supplier_date(self):
        """Дату вхідної ПН визначає постачальник, а не наше правило визнання."""
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.customer_cash.id,
            'invoice_date': '2025-03-10',
            'date': '2025-03-10',
            'invoice_line_ids': [(0, 0, {
                'name': 'послуга', 'quantity': 1, 'price_unit': 1000.0, 'tax_ids': []})],
        })
        bill.action_post()

        # Неоплачений рахунок від контрагента на касовому методі: раніше тут
        # був UserError, тобто вже отриману ПН неможливо було завести взагалі.
        self.assertEqual(bill._l10n_ua_tax_invoice_date(), fields.Date.to_date('2025-03-10'))
        self.assertEqual(bill._l10n_ua_tax_invoice_rule(), 'document')

    def test_credit_note_uses_its_own_date(self):
        """РК складається на дату коригуючої події, а не першої події оригіналу."""
        move = self._invoice(self.customer, '2025-03-10')
        self._pay(move, '2025-03-04')  # передоплата зсунула дату оригінальної ПН
        refund = move._reverse_moves([
            {'invoice_date': '2025-05-20', 'date': '2025-05-20'}])
        refund.action_post()

        refund.action_create_tax_invoice()
        correction = refund.tax_invoice_ids

        self.assertEqual(correction.date, fields.Date.to_date('2025-05-20'))
        self.assertEqual(correction.vat_method, 'document')

    # ------------------------------------------------------------------- ПН

    def test_created_tax_invoice_records_date_and_method(self):
        """Дата ПН береться з правила визнання, а не з дня натискання кнопки."""
        move = self._invoice(self.customer_cash, '2025-03-10')
        self._pay(move, '2025-04-02')

        move.action_create_tax_invoice()
        tax_invoice = move.tax_invoice_ids

        self.assertEqual(len(tax_invoice), 1)
        self.assertEqual(tax_invoice.date, fields.Date.to_date('2025-04-02'))
        self.assertEqual(tax_invoice.vat_method, 'cash')
        self.assertNotEqual(tax_invoice.date, fields.Date.context_today(move),
                             'дата ПН не має дорівнювати сьогоднішній')

    def test_flag_is_company_dependent(self):
        """Ознака належить парі компанія-контрагент, а не контрагенту глобально."""
        other = self.env['res.company'].create({'name': 'Інша компанія'})
        self.env.user.company_ids |= other

        self.assertTrue(self.customer_cash.with_company(self.env.company).l10n_ua_vat_cash_method)
        self.assertFalse(self.customer_cash.with_company(other).l10n_ua_vat_cash_method)
