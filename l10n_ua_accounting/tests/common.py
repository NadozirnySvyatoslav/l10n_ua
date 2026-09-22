"""Common test utilities for l10n_ua_accounting tests."""

from odoo.tests import TransactionCase


class AccountingTestCase(TransactionCase):
    """Base class with shared setup for Ukrainian accounting tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # UA documents (ПКО/ВКО/ПД) are only generated for Ukrainian companies,
        # so the test company must have the country set before journals are made.
        cls.company.country_id = cls.env.ref('base.ua')
        cls.currency = cls.company.currency_id

        # Cash journal
        cls.cash_journal = cls.env['account.journal'].search([
            ('type', '=', 'cash'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Каса (тест)',
                'code': 'CSHT',
                'type': 'cash',
                'company_id': cls.company.id,
            })

        # Bank journal
        cls.bank_journal = cls.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.bank_journal:
            cls.bank_journal = cls.env['account.journal'].create({
                'name': 'Банк (тест)',
                'code': 'BNKT',
                'type': 'bank',
                'company_id': cls.company.id,
            })
        # Ensure UA sequences exist on journals
        cls.cash_journal.action_create_ua_sequences()
        cls.bank_journal.action_create_ua_sequences()

        # General journal for period closing
        cls.misc_journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.misc_journal:
            cls.misc_journal = cls.env['account.journal'].create({
                'name': 'Різне (тест)',
                'code': 'MISC',
                'type': 'general',
                'company_id': cls.company.id,
            })

        # Partner
        cls.partner = cls.env['res.partner'].create({
            'name': 'Тестовий контрагент',
        })

        # Employee (for advance reports)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Тестовий працівник',
            'company_id': cls.company.id,
        })
