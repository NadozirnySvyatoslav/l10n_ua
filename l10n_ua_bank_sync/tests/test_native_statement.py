"""Виписка формується при імпорті як native-сутність (Фаза 1 рефактора)."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNativeStatement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'UA Bank NS', 'type': 'bank', 'code': 'NSBK',
            'company_id': cls.company.id})
        partner = cls.env['res.partner'].create({'name': 'P'})
        cls.acc = cls.env['res.partner.bank'].create({
            'account_number': '26001234567890', 'partner_id': partner.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'NS', 'provider': 'manual',
            'journal_id': cls.journal.id, 'bank_account_id': cls.acc.id})

    def _job(self, **kw):
        vals = {
            'config_id': self.config.id,
            'date_from': '2018-06-01', 'date_to': '2018-06-30',
            'source_type': 'file', 'source_ref': 'iBank2_2018-06.csv',
        }
        vals.update(kw)
        return self.env['l10n_ua.bank.sync.job'].create(vals)

    def _txs(self):
        return [
            {'id': 't1', 'date': '2018-06-01', 'amount': 100.0,
             'description': 'надходження', 'partner_name': 'A',
             'partner_iban': 'UA111'},
            {'id': 't2', 'date': '2018-06-02', 'amount': -30.0,
             'description': 'списання', 'partner_name': 'B',
             'partner_iban': 'UA222'},
        ]

    def test_exchange_type_manual(self):
        self.assertEqual(self.config.exchange_type, 'manual')

    def test_statement_created_at_import_with_metadata(self):
        job = self._job()
        stmt = job._create_native_statement(self._txs())
        self.assertTrue(stmt)
        self.assertEqual(stmt._name, 'account.bank.statement')
        self.assertEqual(len(stmt.line_ids), 2)
        # Метадані джерела зафіксовані при формуванні.
        self.assertEqual(stmt.l10n_ua_source_type, 'file')
        self.assertEqual(stmt.l10n_ua_source_ref, 'iBank2_2018-06.csv')
        self.assertTrue(stmt.l10n_ua_import_date)
        self.assertEqual(stmt.l10n_ua_sync_job_id, job)

    def test_balance_derived_when_no_source(self):
        job = self._job()
        stmt = job._create_native_statement(self._txs())
        # Без балансів джерела → кінцевий баланс виведено, не звірено.
        self.assertFalse(stmt.l10n_ua_balance_verified)
        self.assertAlmostEqual(stmt.balance_start, 0.0, places=2)
        self.assertAlmostEqual(stmt.balance_end, 70.0, places=2)  # 100 − 30
        self.assertFalse(stmt.l10n_ua_balance_ok)

    def test_balance_verified_from_source(self):
        job = self._job()
        stmt = job._create_native_statement(
            self._txs(), opening=1000.0, closing=1070.0)
        self.assertTrue(stmt.l10n_ua_balance_verified)
        self.assertTrue(stmt.l10n_ua_balance_ok)

    def test_balance_mismatch_flagged(self):
        job = self._job()
        stmt = job._create_native_statement(
            self._txs(), opening=1000.0, closing=9999.0)
        self.assertTrue(stmt.l10n_ua_balance_verified)
        # opening + Σ (1070) != closing (9999) → контроль повноти не пройдено.
        self.assertFalse(stmt.l10n_ua_balance_ok)

    def test_idempotent_reimport(self):
        job1 = self._job()
        stmt1 = job1._create_native_statement(self._txs())
        self.assertEqual(len(stmt1.line_ids), 2)
        # Повторний імпорт тих самих рухів (той самий unique_import_id) — дублів немає.
        job2 = self._job()
        stmt2 = job2._create_native_statement(self._txs())
        self.assertFalse(stmt2)  # усі рухи вже імпортовані

    def test_lines_carry_transaction_data(self):
        job = self._job()
        stmt = job._create_native_statement(self._txs())
        line = stmt.line_ids.sorted('amount')[0]  # −30
        self.assertAlmostEqual(line.amount, -30.0, places=2)
        self.assertEqual(line.payment_ref, 'списання')
        self.assertEqual(line.account_number, 'UA222')
        self.assertEqual(line.l10n_ua_import_uid, 't2')

    def test_partner_matched_on_line(self):
        # Контрагент підбирається за IBAN і ставиться на native-рядок.
        partner = self.env['res.partner'].create({'name': 'ТОВ Контрагент'})
        self.env['res.partner.bank'].create({
            'account_number': '26007654321098', 'partner_id': partner.id})
        job = self._job()
        stmt = job._create_native_statement([{
            'id': 'p1', 'date': '2018-06-01', 'amount': 500.0,
            'description': 'оплата', 'partner_name': 'ТОВ Контрагент',
            'partner_iban': '26007654321098'}])
        self.assertEqual(stmt.line_ids.partner_id, partner)
