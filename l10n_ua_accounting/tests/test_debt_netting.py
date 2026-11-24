"""Взаємозалік зустрічних однорідних вимог (#371)."""

from markupsafe import escape

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestDebtNetting(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a
        cls.journal = cls.company_data['default_journal_misc']
        cls.eur = cls.setup_other_currency('EUR')

        def account(code, name, account_type):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': account_type,
                'reconcile': True, 'company_ids': [Command.link(cls.company.id)]})
        # 371 у плані рахунків — `asset_current`, а не receivable.
        cls.acc_371 = account('371100', 'Аванси видані', 'asset_current')
        cls.acc_685 = account('685100', 'Інші кредитори', 'liability_payable')
        cls.acc_other = cls.company_data['default_account_revenue']

    # ------------------------------------------------------------ helpers

    def _doc(self, move_type, amount, date='2025-03-01', currency=None,
             partner=None):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': (partner or self.partner).id,
            'invoice_date': date,
            'date': date,
            'currency_id': (currency or self.company.currency_id).id,
            'invoice_line_ids': [Command.create({
                'name': 'послуга', 'quantity': 1, 'price_unit': amount,
                'tax_ids': [],
            })],
        })
        move.action_post()
        return move

    def _entry(self, account, amount, date='2025-03-01'):
        """Ручна проводка на розрахунковому рахунку: amount > 0 — дебет."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [
                Command.create({
                    'name': 'розрахунки', 'account_id': account.id,
                    'partner_id': self.partner.id, 'balance': amount}),
                Command.create({
                    'name': 'кореспонденція', 'account_id': self.acc_other.id,
                    'balance': -amount}),
            ],
        })
        move.action_post()
        return move

    def _netting(self, currency=None, date='2025-03-31', fill=True, **kw):
        netting = self.env['l10n_ua.debt.netting'].create({
            'partner_id': self.partner.id,
            'journal_id': self.journal.id,
            'date': date,
            'currency_id': (currency or self.company.currency_id).id,
            **kw,
        })
        if fill:
            netting.action_fill_lines()
        return netting

    @staticmethod
    def _settlement_line(move):
        return move.line_ids.filtered(lambda l: l.account_id.reconcile)

    # ------------------------------------------------------------ scenarios

    def test_full_offset(self):
        invoice = self._doc('out_invoice', 1000.0)
        bill = self._doc('in_invoice', 1000.0)
        netting = self._netting()
        self.assertEqual(len(netting.receivable_line_ids), 1)
        self.assertEqual(len(netting.payable_line_ids), 1)
        self.assertAlmostEqual(netting.amount_max, 1000.0)
        self.assertAlmostEqual(netting.amount, 1000.0)
        self.assertNotEqual(netting.name, '/')

        netting.action_post()
        self.assertEqual(netting.state, 'posted')
        move = netting.move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.partner_id, self.partner)
        receivable = self._settlement_line(invoice).account_id
        payable = self._settlement_line(bill).account_id
        # Дт 631 — Кт 361 на суму заліку, контрагент на обох рядках
        self.assertRecordValues(move.line_ids.sorted('balance'), [
            {'account_id': receivable.id, 'balance': -1000.0,
             'partner_id': self.partner.id, 'reconciled': True},
            {'account_id': payable.id, 'balance': 1000.0,
             'partner_id': self.partner.id, 'reconciled': True},
        ])
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))

    def test_partial_offset_fifo(self):
        inv_old = self._doc('out_invoice', 300.0, date='2025-01-10')
        inv_new = self._doc('out_invoice', 700.0, date='2025-02-10')
        bill = self._doc('in_invoice', 500.0, date='2025-02-15')
        netting = self._netting()
        self.assertAlmostEqual(netting.amount_receivable, 1000.0)
        self.assertAlmostEqual(netting.amount_payable, 500.0)
        self.assertAlmostEqual(netting.amount, 500.0)
        # FIFO: спершу найстаріший документ
        offsets = {l.move_id: l.amount_offset for l in netting.line_ids}
        self.assertAlmostEqual(offsets[inv_old], 300.0)
        self.assertAlmostEqual(offsets[inv_new], 200.0)
        self.assertAlmostEqual(offsets[bill], 500.0)

        netting.action_post()
        self.assertAlmostEqual(inv_old.amount_residual, 0.0)
        self.assertAlmostEqual(inv_new.amount_residual, 500.0)
        self.assertAlmostEqual(bill.amount_residual, 0.0)
        self.assertEqual(inv_new.payment_state, 'partial')
        self.assertAlmostEqual(
            sum(netting.move_id.line_ids.filtered(
                lambda l: l.balance > 0).mapped('balance')), 500.0)

    def test_user_amount_below_maximum(self):
        invoice = self._doc('out_invoice', 1000.0)
        bill = self._doc('in_invoice', 800.0)
        netting = self._netting()
        netting.amount = 250.0
        netting.action_post()
        self.assertAlmostEqual(netting.amount, 250.0)
        self.assertAlmostEqual(invoice.amount_residual, 750.0)
        self.assertAlmostEqual(bill.amount_residual, 550.0)

    def test_amount_above_maximum_rejected(self):
        self._doc('out_invoice', 1000.0)
        self._doc('in_invoice', 800.0)
        netting = self._netting()
        with self.assertRaises(ValidationError):
            netting.amount = 900.0
            netting.flush_recordset()

    def test_one_side_only_rejected(self):
        self._doc('out_invoice', 1000.0)
        netting = self._netting()
        with self.assertRaises(UserError):
            netting.action_post()

    def test_different_accounts_371_685(self):
        advance = self._entry(self.acc_371, 400.0)
        creditor = self._entry(self.acc_685, -650.0)
        netting = self._netting()
        self.assertEqual(netting.receivable_line_ids.account_id, self.acc_371)
        self.assertEqual(netting.payable_line_ids.account_id, self.acc_685)
        self.assertAlmostEqual(netting.amount, 400.0)
        netting.action_post()
        self.assertRecordValues(netting.move_id.line_ids.sorted('balance'), [
            {'account_id': self.acc_371.id, 'balance': -400.0},
            {'account_id': self.acc_685.id, 'balance': 400.0},
        ])
        adv_line = advance.line_ids.filtered(
            lambda l: l.account_id == self.acc_371)
        cred_line = creditor.line_ids.filtered(
            lambda l: l.account_id == self.acc_685)
        self.assertTrue(adv_line.reconciled)
        self.assertAlmostEqual(cred_line.amount_residual, -250.0)

    def test_foreign_currency(self):
        # Курс: 2016 — 3 EUR за одиницю валюти компанії, 2017 — 2 EUR.
        invoice = self._doc('out_invoice', 300.0, date='2016-06-01',
                            currency=self.eur)
        bill = self._doc('in_invoice', 300.0, date='2017-02-01',
                         currency=self.eur)
        self._doc('in_invoice', 50.0, date='2017-02-01')  # інша валюта
        netting = self._netting(currency=self.eur, date='2017-03-01')
        self.assertEqual(len(netting.line_ids), 2)
        self.assertAlmostEqual(netting.amount, 300.0)
        netting.action_post()
        move = netting.move_id
        # Обидві сторони за курсом на дату заліку: 300 / 2 = 150
        self.assertRecordValues(move.line_ids.sorted('balance'), [
            {'amount_currency': -300.0, 'balance': -150.0,
             'currency_id': self.eur.id},
            {'amount_currency': 300.0, 'balance': 150.0,
             'currency_id': self.eur.id},
        ])
        inv_line = self._settlement_line(invoice)
        bill_line = self._settlement_line(bill)
        self.assertTrue(inv_line.reconciled)
        self.assertTrue(bill_line.reconciled)
        self.assertAlmostEqual(inv_line.amount_residual_currency, 0.0)

    def test_line_in_other_currency_rejected(self):
        bill = self._doc('in_invoice', 100.0)
        netting = self._netting(currency=self.eur, fill=False)
        with self.assertRaises(ValidationError):
            netting.line_ids = [Command.create({
                'move_line_id': self._settlement_line(bill).id})]

    def test_line_of_other_partner_rejected(self):
        bill = self._doc('in_invoice', 100.0, partner=self.partner_b)
        netting = self._netting(fill=False)
        with self.assertRaises(ValidationError):
            netting.line_ids = [Command.create({
                'move_line_id': self._settlement_line(bill)[:1].id})]

    def test_cancel_restores_residuals(self):
        invoice = self._doc('out_invoice', 1000.0)
        bill = self._doc('in_invoice', 600.0)
        netting = self._netting()
        netting.action_post()
        self.assertAlmostEqual(invoice.amount_residual, 400.0)

        netting.action_cancel()
        self.assertEqual(netting.state, 'cancel')
        self.assertTrue(netting.reversal_move_id)
        self.assertEqual(netting.reversal_move_id.state, 'posted')
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertAlmostEqual(bill.amount_residual, 600.0)
        self.assertEqual(invoice.payment_state, 'not_paid')
        # Проводка і сторно взаємно зіставлені й не висять у відкритих
        self.assertTrue(all(netting.move_id.line_ids.mapped('reconciled')))

        with self.assertRaises(UserError):
            netting.action_post()
        netting.action_draft()
        self.assertFalse(netting.move_id)
        netting.action_post()
        self.assertAlmostEqual(invoice.amount_residual, 400.0)

    def test_post_refreshes_open_amounts(self):
        invoice = self._doc('out_invoice', 1000.0)
        self._doc('in_invoice', 900.0)
        netting = self._netting()
        self.assertAlmostEqual(netting.amount, 900.0)
        # Рахунок частково оплатили, поки чернетка лежала
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'amount': 300.0, 'payment_date': '2025-03-15'})._create_payments()
        with self.assertRaises(UserError):
            netting.action_post()
        self.env.invalidate_all()
        netting.amount = 700.0
        netting.action_post()
        self.assertAlmostEqual(
            netting.receivable_line_ids.amount_open, 700.0)
        self.assertAlmostEqual(invoice.amount_residual, 0.0)

    def test_posted_cannot_be_deleted(self):
        self._doc('out_invoice', 100.0)
        self._doc('in_invoice', 100.0)
        netting = self._netting()
        netting.action_post()
        with self.assertRaises(UserError):
            netting.unlink()

    def test_vat_cash_method_sees_netting(self):
        """Залік — перша подія для касового методу ПДВ (п. 187.10 ПКУ)."""
        invoice = self._doc('out_invoice', 1000.0, date='2025-03-01')
        self._doc('in_invoice', 1000.0, date='2025-03-02')
        netting = self._netting(date='2025-03-20')
        netting.action_post()
        self.assertEqual(invoice._l10n_ua_first_payment_date(),
                         fields.Date.to_date('2025-03-20'))

    def test_reconciliation_act_shows_netting(self):
        self._doc('out_invoice', 1000.0)
        self._doc('in_invoice', 400.0)
        netting = self._netting()
        netting.action_post()
        wizard = self.env['l10n_ua.reconciliation.act.wizard'].create({
            'partner_id': self.partner.id,
            'date_from': '2025-01-01',
            'date_to': '2025-12-31',
        })
        data = wizard._get_report_data()
        refs = [line['ref'] for line in data['lines']]
        self.assertEqual(refs.count(netting.move_id.name), 2)
        # Залік не змінює сальдо: 1000 - 400 = 600 на користь компанії
        self.assertAlmostEqual(data['closing_balance'], 600.0)

    def test_print_act(self):
        self._doc('out_invoice', 1234.56)
        self._doc('in_invoice', 2000.0)
        netting = self._netting()
        netting.action_post()
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.action_report_debt_netting', netting.ids)
        html = html.decode()
        self.assertIn('взаємозаліку зустрічних однорідних вимог', html)
        self.assertIn(netting.name, html)
        self.assertIn('601', html)
        self.assertIn(netting._get_print_amount(1234.56), html)
        # t-out escapes the apostrophe of «п'ятдесят» in a currency amount.
        self.assertIn(str(escape(netting._get_amount_words())), html)

    def test_form_manual_selection(self):
        """Ручний вибір документів у формі: розподіл рахується на льоту."""
        invoice = self._doc('out_invoice', 1000.0)
        bill = self._doc('in_invoice', 300.0)
        form = Form(self.env['l10n_ua.debt.netting'])
        form.partner_id = self.partner
        form.journal_id = self.journal
        with form.receivable_line_ids.new() as line:
            line.move_line_id = self._settlement_line(invoice)
        with form.payable_line_ids.new() as line:
            line.move_line_id = self._settlement_line(bill)
        self.assertAlmostEqual(form.amount_max, 300.0)
        self.assertAlmostEqual(form.amount, 300.0)
        form.amount = 120.0
        netting = form.save()
        self.assertAlmostEqual(netting.amount, 120.0)
        self.assertAlmostEqual(netting.receivable_line_ids.amount_offset, 120.0)
        self.assertAlmostEqual(netting.receivable_line_ids.amount_after, 880.0)
        netting.action_post()
        self.assertAlmostEqual(invoice.amount_residual, 880.0)
        self.assertAlmostEqual(bill.amount_residual, 180.0)
