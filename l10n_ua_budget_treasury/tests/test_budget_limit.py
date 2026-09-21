"""Tests for treasury journals + budget-limit enforcement on posting."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_budget_treasury')
class TestBudgetLimitChecker(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.kekv_2111 = cls.env.ref('l10n_ua_budget_base.kekv_2111')
        cls.kekv_2273 = cls.env.ref('l10n_ua_budget_base.kekv_2273')
        cls.kpkvk = cls.env.ref('l10n_ua_budget_base.kpkvk_2201190_2025')
        cls.organ_central = cls.env.ref('l10n_ua_budget_treasury.organ_central')

        # A treasury journal — minimal bank journal flagged as ua_is_treasury
        cls.expense_acct = cls.env['account.account'].search(
            [('account_type', '=', 'expense'),
             ('company_ids', 'parent_of', cls.company.id)], limit=1)
        cls.liab_acct = cls.env['account.account'].search(
            [('account_type', '=', 'liability_current'),
             ('company_ids', 'parent_of', cls.company.id)], limit=1)

        cls.journal = cls.env['account.journal'].create({
            'name': 'TEST Treasury',
            'type': 'bank',
            'code': 'TTRZ',
            'company_id': cls.company.id,
            'ua_is_treasury': True,
            'ua_treasury_account_type': 'registration',
            'ua_treasury_organ_id': cls.organ_central.id,
            'ua_treasury_fund_type': 'general',
            'ua_treasury_check_limit': True,
        })

        # Approved estimate with 5000 UAH on КЕКВ 2111 / general fund
        cls.estimate = cls.env['l10n_ua.budget.estimate'].create({
            'title': 'TEST estimate 2025',
            'year': 2025,
            'fund_type': 'general',
            'kpkvk_id': cls.kpkvk.id,
            'line_ids': [(0, 0, {
                'kekv_id': cls.kekv_2111.id,
                'fund_type': 'general',
                'kpkvk_id': cls.kpkvk.id,
                'm01': 5000,
            })],
        })
        cls.estimate.action_submit()
        cls.estimate.action_approve()

    def _make_entry(self, debit_amount, kekv=None, kpkvk=None, fund='general'):
        """Create a draft journal entry on the treasury journal."""
        return self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {
                    'account_id': self.expense_acct.id,
                    'name': 'expense', 'debit': debit_amount, 'credit': 0,
                    'ua_kekv_id': (kekv or self.kekv_2111).id,
                    'ua_kpkvk_id': (kpkvk or self.kpkvk).id,
                    'ua_fund_type': fund,
                }),
                (0, 0, {
                    'account_id': self.liab_acct.id,
                    'name': 'payable', 'debit': 0, 'credit': debit_amount,
                    'ua_kekv_id': (kekv or self.kekv_2111).id,
                    'ua_kpkvk_id': (kpkvk or self.kpkvk).id,
                    'ua_fund_type': fund,
                }),
            ],
        })

    def test_within_limit_posts(self):
        move = self._make_entry(3000.0)
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_over_limit_blocks(self):
        move = self._make_entry(7000.0)  # plan is 5000
        with self.assertRaises(UserError) as cm:
            move.action_post()
        self.assertIn('Перевищення', cm.exception.args[0])

    def test_missing_estimate_blocks(self):
        # КЕКВ 2273 has no estimate line — should block
        move = self._make_entry(100.0, kekv=self.kekv_2273)
        with self.assertRaises(UserError) as cm:
            move.action_post()
        self.assertIn('Немає затвердженого кошторису', cm.exception.args[0])

    def test_check_skipped_when_disabled(self):
        """If ua_treasury_check_limit is off, even big amounts pass."""
        self.journal.ua_treasury_check_limit = False
        move = self._make_entry(99999.0)
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_non_treasury_journal_not_blocked(self):
        """Posting on non-treasury journal must not invoke the limit checker."""
        plain_journal = self.env['account.journal'].create({
            'name': 'Plain bank', 'type': 'bank', 'code': 'PLN',
            'company_id': self.company.id, 'ua_is_treasury': False,
        })
        move = self._make_entry(99999.0)
        move.journal_id = plain_journal
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_aggregates_within_one_move(self):
        """Two lines on same КЕКВ should be summed, not checked separately."""
        # Plan is 5000. Two lines each 3000 → total 6000 → should fail.
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {
                    'account_id': self.expense_acct.id,
                    'name': 'half 1', 'debit': 3000, 'credit': 0,
                    'ua_kekv_id': self.kekv_2111.id,
                    'ua_kpkvk_id': self.kpkvk.id,
                    'ua_fund_type': 'general',
                }),
                (0, 0, {
                    'account_id': self.expense_acct.id,
                    'name': 'half 2', 'debit': 3000, 'credit': 0,
                    'ua_kekv_id': self.kekv_2111.id,
                    'ua_kpkvk_id': self.kpkvk.id,
                    'ua_fund_type': 'general',
                }),
                (0, 0, {
                    'account_id': self.liab_acct.id,
                    'name': 'payable', 'debit': 0, 'credit': 6000,
                }),
            ],
        })
        with self.assertRaises(UserError):
            move.action_post()


@tagged('post_install', '-at_install', 'l10n_ua_budget_treasury')
class TestTreasuryOrganSeed(TransactionCase):

    def test_seed_loaded(self):
        Organ = self.env['l10n_ua.treasury.organ']
        self.assertTrue(Organ.search_count([('code', '=', 'DKSU')]))
        self.assertGreaterEqual(Organ.search_count([('organ_type', '=', 'regional')]), 25)

    def test_hierarchy(self):
        kyiv = self.env.ref('l10n_ua_budget_treasury.organ_kyiv')
        self.assertEqual(kyiv.parent_id.code, 'DKSU')


@tagged('post_install', '-at_install', 'l10n_ua_budget_treasury')
class TestStatementImport(TransactionCase):

    def test_csv_import(self):
        """End-to-end: wizard ingests minimal CSV and creates a bank statement."""
        import base64
        company = self.env.company
        journal = self.env['account.journal'].create({
            'name': 'TEST treasury for import', 'type': 'bank', 'code': 'TIMP',
            'company_id': company.id, 'ua_is_treasury': True,
            'ua_treasury_account_type': 'registration',
            'ua_treasury_fund_type': 'general',
            'ua_treasury_check_limit': False,
        })
        csv_content = (
            "date,description,partner_name,amount,reference\n"
            "2025-01-10,Salary payment,ACME LLC,1500.50,REF001\n"
            "2025-01-15,Refund,Bob,-50.00,REF002\n"
        )
        wizard = self.env['l10n_ua.treasury.statement.import'].create({
            'journal_id': journal.id,
            'file': base64.b64encode(csv_content.encode('utf-8')).decode(),
            'filename': 'demo.csv',
            'file_format': 'csv',
            'encoding': 'utf-8',
        })
        result = wizard.action_import()
        self.assertEqual(result['res_model'], 'account.bank.statement')
        statement = self.env['account.bank.statement'].browse(result['res_id'])
        self.assertEqual(statement.journal_id, journal)
        self.assertEqual(len(statement.line_ids), 2)
        self.assertEqual(statement.line_ids[0].amount + statement.line_ids[1].amount, 1450.50)

    def test_bad_csv_raises(self):
        import base64
        company = self.env.company
        journal = self.env['account.journal'].create({
            'name': 'TEST treasury bad csv', 'type': 'bank', 'code': 'TBAD',
            'company_id': company.id, 'ua_is_treasury': True,
        })
        bad_content = "wrong,headers\n2025-01-10,whatever\n"
        wizard = self.env['l10n_ua.treasury.statement.import'].create({
            'journal_id': journal.id,
            'file': base64.b64encode(bad_content.encode('utf-8')).decode(),
            'filename': 'bad.csv', 'file_format': 'csv',
        })
        with self.assertRaises(UserError):
            wizard.action_import()
