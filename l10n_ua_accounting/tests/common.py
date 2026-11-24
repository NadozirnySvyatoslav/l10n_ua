"""Common test utilities for l10n_ua_accounting tests."""

from odoo.tests import TransactionCase


class AccountingTestCase(TransactionCase):
    """Base class with shared setup for Ukrainian accounting tests.

    ``_own_company = True`` runs the class on a fresh UA company with the
    ua_psbo chart instead of ``env.company``: on a demo database the current
    company is the generic «My Company» with stock, bank statements and
    balances that leak into the tests (#654, #666).
    """

    _own_company = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls._own_company:
            company = cls.env['res.company'].create({
                'name': f'UA test ({cls.__name__})',
                'country_id': cls.env.ref('base.ua').id,
            })
            cls.env['account.chart.template'].try_loading(
                'ua_psbo', company=company, install_demo=False)
            cls.env.user.company_ids |= company
            cls.env.user.company_id = company
            cls.env = cls.env(context=dict(
                cls.env.context, allowed_company_ids=[company.id]))
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

    def assertXlsxExport(self, action):
        """Дія експорту має вести на вкладення з непорожнім xlsx-файлом."""
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        att_id = int(action['url'].split('/web/content/')[1].split('?')[0])
        attachment = self.env['ir.attachment'].browse(att_id)
        self.assertTrue(attachment.exists())
        # xlsx — це zip-архів, сигнатура PK
        # bytes(): у Odoo 20 raw — обгортка BinaryFile, не bytes
        content = bytes(attachment.raw or b'')
        self.assertEqual(content[:2], b'PK', 'Вкладення має містити xlsx-файл')
        return attachment
