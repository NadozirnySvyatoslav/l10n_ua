"""Multi-company isolation for UA bank-sync records — issue #178.

Bank-sync records carry company_id but had no multi-company ir.rule, so they
leaked across ALL companies (including non-UA ones). These tests assert the
global multi-company rules scope each record to the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSyncMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})

        # Bank journal in the UA company (config requires a bank journal).
        cls.journal_ua = cls.env['account.journal'].create({
            'name': 'UA Bank', 'type': 'bank', 'code': 'UABK',
            'company_id': cls.company_ua.id})
        cls.journal_other = cls.env['account.journal'].create({
            'name': 'Other Bank', 'type': 'bank', 'code': 'OTBK',
            'company_id': cls.company_other.id})

        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'banksync_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('l10n_ua_account_base.group_ua_accountant').id])],
        })

    def _config(self, company, journal):
        return self.env['l10n_ua.bank.sync.config'].create({
            'name': 'Cfg %s' % company.name,
            'provider': 'manual',
            'journal_id': journal.id,
            'company_id': company.id,
        })

    def test_other_company_user_cannot_see_ua_config(self):
        """A user of the non-UA company must not see the UA company's config."""
        cfg = self._config(self.company_ua, self.journal_ua)
        visible = self.env['l10n_ua.bank.sync.config'].with_user(
            self.user_other).search([])
        self.assertNotIn(cfg, visible)

    def test_same_company_user_sees_own_config(self):
        """The rule still lets a user see their own company's config."""
        cfg = self._config(self.company_other, self.journal_other)
        visible = self.env['l10n_ua.bank.sync.config'].with_user(
            self.user_other).search([])
        self.assertIn(cfg, visible)

    def test_rules_exist_and_global(self):
        """Remaining bank-sync models must have a global multi-company rule."""
        for xmlid in (
            'l10n_ua_bank_sync_config_company_rule',
            'l10n_ua_bank_sync_job_company_rule',
        ):
            rule = self.env.ref('l10n_ua_bank_sync.%s' % xmlid)
            self.assertEqual(
                rule.kind, 'restriction',
                '%s must be a restriction' % xmlid)
