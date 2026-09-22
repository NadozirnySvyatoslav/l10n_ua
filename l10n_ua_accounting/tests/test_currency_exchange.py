"""Операції купівлі/продажу валюти (#205)."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestCurrencyExchange(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Валюта операції має відрізнятися від валюти компанії — цього вимагає
        # і домен самого поля (`[('id', '!=', currency_id)]`), і Odoo: для
        # рядка у валюті компанії balance нормалізується до amount_currency,
        # тож Дт 312 став би 1000 замість 40000 і проводка розбалансувалась би.
        # У типовій `My Company` валюта компанії — USD, тож просто взяти
        # `base.USD` не можна (перепризначити валюту компанії теж: account
        # забороняє це, щойно в базі є хоч один рядок проводки).
        cls.fx_currency = cls.env.ref('base.USD')
        if cls.fx_currency == cls.company.currency_id:
            cls.fx_currency = cls.env.ref('base.EUR')

        def acc(code, name, atype):
            # chart_template_load: див. test_cashflow — інакше кожен
            # asset_cash родить банківський журнал, і другий падає на
            # неунікальному поштовому аліасі.
            return cls.env['account.account'].with_context(
                chart_template_load=True).create({
                'code': code, 'name': name, 'account_type': atype,
                'company_ids': [(4, cls.company.id)]})
        cls.acc_312 = acc('3120X', 'Валютний рахунок', 'asset_cash')
        cls.acc_311 = acc('3110X', 'Поточний рахунок', 'asset_cash')
        cls.acc_711 = acc('7110X', 'Дохід від валюти', 'income_other')
        cls.acc_942 = acc('9420X', 'Витрати від валюти', 'expense')
        cls.acc_92 = acc('9200X', 'Комісія', 'expense')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Валюта', 'type': 'general', 'code': 'FXJ',
            'company_id': cls.company.id})

    def _exchange(self, op='purchase', **kw):
        vals = {
            'operation_type': op,
            'date': date(2025, 6, 10),
            'foreign_currency_id': self.fx_currency.id,
            'fc_amount': 1000.0,
            'commercial_rate': 41.0,
            'nbu_rate': 40.0,
            'commission': 200.0,
            'company_id': self.company.id,
            'journal_id': self.journal.id,
            'foreign_account_id': self.acc_312.id,
            'current_account_id': self.acc_311.id,
            'commission_account_id': self.acc_92.id,
            'gain_account_id': self.acc_711.id,
            'loss_account_id': self.acc_942.id,
        }
        vals.update(kw)
        return self.env['l10n_ua.currency.exchange'].create(vals)

    # --- Розрахунок ---

    def test_amounts_purchase(self):
        rec = self._exchange('purchase')
        self.assertAlmostEqual(rec.uah_amount, 41000.0, places=2)
        self.assertAlmostEqual(rec.nbu_value, 40000.0, places=2)
        # Купівля дорожче за НБУ → витрати (від'ємний результат)
        self.assertAlmostEqual(rec.fx_result, -1000.0, places=2)

    def test_amounts_sale(self):
        rec = self._exchange('sale')
        # Продаж дорожче за НБУ → дохід
        self.assertAlmostEqual(rec.fx_result, 1000.0, places=2)

    # --- Проведення ---

    def test_post_purchase(self):
        rec = self._exchange('purchase')
        rec.action_post()
        self.assertEqual(rec.state, 'posted')
        move = rec.move_id
        self.assertTrue(move and move.state == 'posted')
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')), places=2)
        line_312 = move.line_ids.filtered(lambda l: l.account_id == self.acc_312)
        self.assertAlmostEqual(line_312.debit, 40000.0, places=2)
        self.assertAlmostEqual(line_312.amount_currency, 1000.0, places=2)
        self.assertEqual(line_312.currency_id, self.fx_currency)
        line_311 = move.line_ids.filtered(lambda l: l.account_id == self.acc_311)
        self.assertAlmostEqual(line_311.credit, 41200.0, places=2)
        line_loss = move.line_ids.filtered(lambda l: l.account_id == self.acc_942)
        self.assertAlmostEqual(line_loss.debit, 1000.0, places=2)
        line_comm = move.line_ids.filtered(lambda l: l.account_id == self.acc_92)
        self.assertAlmostEqual(line_comm.debit, 200.0, places=2)

    def test_post_sale(self):
        rec = self._exchange('sale')
        rec.action_post()
        move = rec.move_id
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')), places=2)
        line_312 = move.line_ids.filtered(lambda l: l.account_id == self.acc_312)
        self.assertAlmostEqual(line_312.credit, 40000.0, places=2)
        self.assertAlmostEqual(line_312.amount_currency, -1000.0, places=2)
        line_311 = move.line_ids.filtered(lambda l: l.account_id == self.acc_311)
        # Виручка мінус комісія: 41000 - 200 = 40800
        self.assertAlmostEqual(line_311.debit, 40800.0, places=2)
        line_gain = move.line_ids.filtered(lambda l: l.account_id == self.acc_711)
        self.assertAlmostEqual(line_gain.credit, 1000.0, places=2)

    def test_draft_removes_move(self):
        rec = self._exchange('purchase')
        rec.action_post()
        rec.action_draft()
        self.assertEqual(rec.state, 'draft')
        self.assertFalse(rec.move_id)

    def test_nbu_rate_required(self):
        rec = self._exchange('purchase', nbu_rate=0.0)
        with self.assertRaises(UserError):
            rec.action_post()

    def test_positive_amount(self):
        with self.assertRaises(UserError):
            self._exchange('purchase', fc_amount=0.0)
