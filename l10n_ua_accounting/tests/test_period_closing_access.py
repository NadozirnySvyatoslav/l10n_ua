"""Межа прав на закриття періоду — issue #694, ADR 0004.

Бухгалтер готує закриття (чернетка, «Розрахувати»), закриває і сторнує
його лише головбух: закриття пише стан податкового періоду і через sudo
рухає дату блокування компанії.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestPeriodClosingAccess(AccountingTestCase):

    _own_company = True  # #654: demo unreconciled statement lines block the lock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_92 = cls._account('92', 'Адміністративні витрати', 'expense')
        cls.acc_631 = cls._account('631', 'Розрахунки з постачальниками', 'liability_payable')
        cls.acc_791 = cls._account('791', 'Результат операційної діяльності', 'equity')
        cls.acc_792 = cls._account('792', 'Результат фінансових операцій', 'equity')
        cls.acc_793 = cls._account('793', 'Результат іншої діяльності', 'equity')
        cls.acc_441 = cls._account('4411', 'Нерозподілений прибуток', 'equity')
        cls.acc_442 = cls._account('4421', 'Непокриті збитки', 'equity')
        cls.company.fiscalyear_lock_date = date(2034, 12, 31)

        def user(login, group):
            return new_test_user(
                cls.env, login=login, groups=f'base.group_user,{group}',
                company_id=cls.company.id, company_ids=[(6, 0, cls.company.ids)])

        cls.accountant = user('ua_acc_694', 'l10n_ua_account_base.group_ua_accountant')
        cls.tax_accountant = user('ua_tax_694', 'l10n_ua_account_base.group_ua_tax_accountant')
        cls.chief = user('ua_chief_694', 'l10n_ua_account_base.group_ua_manager')

    @classmethod
    def _account(cls, code, name, account_type):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [(6, 0, cls.company.ids)],
            'reconcile': account_type == 'liability_payable',
        })

    def setUp(self):
        super().setUp()
        self.period = self.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(2035, 3, 1),
            'date_end': date(2035, 3, 31),
            'company_id': self.company.id,
        })
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': date(2035, 3, 10),
            'line_ids': [
                (0, 0, {'account_id': self.acc_92.id, 'debit': 1000.0,
                        'partner_id': self.partner.id}),
                (0, 0, {'account_id': self.acc_631.id, 'credit': 1000.0,
                        'partner_id': self.partner.id}),
            ],
        })
        move.action_post()

    def _closing(self, user):
        return self.env['l10n_ua.period.closing'].with_user(user).create({
            'period_id': self.period.id,
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
            'account_791_id': self.acc_791.id,
            'account_792_id': self.acc_792.id,
            'account_793_id': self.acc_793.id,
            'account_profit_id': self.acc_441.id,
            'account_loss_id': self.acc_442.id,
        })

    def _assert_untouched(self, closing):
        self.assertEqual(closing.state, 'draft')
        self.assertEqual(self.period.state, 'open')
        self.assertEqual(self.company.fiscalyear_lock_date, date(2034, 12, 31))
        self.assertFalse(closing.closing_move_id)

    def test_accountant_prepares_closing(self):
        """Бухгалтер відкриває форму і рахує закриття без AccessError."""
        closing = self._closing(self.accountant)
        closing.read(['name', 'period_id', 'state', 'date'])
        self.assertEqual(closing.period_id.display_name, self.period.display_name)
        closing.action_compute()
        self.assertTrue(closing.closing_line_ids)

    def test_accountant_cannot_close(self):
        for user in (self.accountant, self.tax_accountant):
            with self.subTest(user=user.login):
                closing = self._closing(user)
                with self.assertRaisesRegex(UserError, 'chief accountant'):
                    closing.action_close()
                self._assert_untouched(closing.sudo())
                closing.sudo().unlink()

    def test_chief_closes_and_reverses(self):
        closing = self._closing(self.accountant)
        closing.action_compute()

        closing.with_user(self.chief).action_close()
        self.assertEqual(closing.state, 'closed')
        self.assertEqual(self.period.state, 'closed')
        self.assertEqual(self.company.fiscalyear_lock_date, date(2035, 3, 31))

        for user in (self.accountant, self.tax_accountant):
            with self.subTest(user=user.login):
                with self.assertRaisesRegex(UserError, 'chief accountant'):
                    closing.with_user(user).action_reverse()
                self.assertEqual(closing.state, 'closed')
                self.assertEqual(self.company.fiscalyear_lock_date, date(2035, 3, 31))

        closing.with_user(self.chief).action_reverse()
        self.assertEqual(closing.state, 'reversed')
        self.assertEqual(self.period.state, 'open')
        self.assertEqual(self.company.fiscalyear_lock_date, date(2034, 12, 31))

    def test_close_buttons_only_for_chief(self):
        def buttons(user):
            arch = self.env['l10n_ua.period.closing'].with_user(user).get_views(
                [(False, 'form')])['views']['form']['arch']
            return {name for name in ('action_close', 'action_reverse', 'action_compute')
                    if f'name="{name}"' in arch}

        self.assertEqual(buttons(self.accountant), {'action_compute'})
        self.assertEqual(buttons(self.chief),
                         {'action_close', 'action_reverse', 'action_compute'})
