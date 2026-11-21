"""The vacation chain starts at the opening balance or the recorded
history, not at the hire date (#629)."""
import importlib.util
import os
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestVacationOpeningBalance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.annual = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.annual.write({
            'requires_experience': False, 'is_transferable': True,
            'max_transfer_days': 0, 'annual_days': 24,
        })
        cls.Balance = cls.env['hr.vacation.balance']
        cls.employee = cls._hire('Працівник з 2017', date(2017, 3, 1))
        cls.today = fields.Date.today()

    @classmethod
    def _hire(cls, name, start):
        employee = cls.env['hr.employee'].create({'name': name})
        version = employee.with_context(active_test=False).version_ids[:1]
        version.write({'contract_date_start': start,
                       'contract_date_end': False})
        return employee

    def _chain(self, employee=None):
        return self.Balance.search([
            ('employee_id', '=', (employee or self.employee).id),
            ('leave_type_id', '=', self.annual.id),
        ], order='period_start')

    def _current_start(self):
        start = date(self.today.year, 3, 1)
        return start if start <= self.today else start - relativedelta(years=1)

    def test_no_history_starts_at_current_period(self):
        """Nine years of employment without any vacation in Odoo used to give
        9 × 24 = 216 "unused" days; now only the current work year exists."""
        self.Balance.generate_balances(leave_types=self.annual)
        chain = self._chain()
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain.period_start, self._current_start())
        self.assertEqual(chain.carried_over, 0)
        self.assertEqual(chain.remaining_days, 24)

    def test_chain_starts_at_first_recorded_leave(self):
        leave = self.env['hr.leave'].create({
            'name': 'Відпустка 2023',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.annual.id,
            'request_date_from': date(2023, 7, 3),
            'request_date_to': date(2023, 7, 16),
        })
        leave.sudo().state = 'validate'
        self.Balance.generate_balances(leave_types=self.annual)
        chain = self._chain()
        self.assertEqual(chain[0].period_start, date(2023, 3, 1))
        self.assertEqual(chain[0].carried_over, 0)
        self.assertEqual(chain[0].used_days, 14)
        self.assertEqual(chain[1].carried_over, 10)

    def test_opening_balance_of_employee(self):
        self.employee.write({
            'l10n_ua_vacation_opening_date': date(2024, 3, 1),
            'l10n_ua_vacation_opening_days': 10,
        })
        self.Balance.generate_balances(leave_types=self.annual)
        chain = self._chain()
        self.assertEqual(chain[0].period_start, date(2024, 3, 1))
        self.assertEqual(chain[0].carried_over, 10)
        self.assertEqual(chain[1].carried_over, 34)

    def test_opening_balance_ignores_older_periods(self):
        """A period before the opening date (e.g. generated earlier) feeds
        nothing into the chain; the opening days do."""
        old = self.Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual.id,
            'period_start': date(2018, 3, 1),
            'period_end': date(2019, 2, 28),
            'period_index': 2,
            'entitled_days': 24,
        })
        self.employee.write({
            'l10n_ua_vacation_opening_date': date(2024, 3, 1),
            'l10n_ua_vacation_opening_days': 5,
        })
        chain = self._chain()
        opening = chain.filtered(lambda b: b.period_start == date(2024, 3, 1))
        self.assertTrue(opening, 'the opening period is created on write')
        self.assertEqual(opening.carried_over, 5)
        self.assertNotIn(date(2019, 3, 1), chain.mapped('period_start'))
        self.assertEqual(old.remaining_days, 24)

    def test_company_accounting_start(self):
        self.env.company.l10n_ua_vacation_accounting_start = date(2025, 1, 1)
        self.Balance.generate_balances(leave_types=self.annual)
        chain = self._chain()
        self.assertEqual(chain[0].period_start, date(2024, 3, 1))
        self.assertEqual(chain[0].carried_over, 0)

    def test_migration_drops_backfilled_periods(self):
        """Periods backfilled from the hire date by the old code, with no
        leave on them, are removed; the chain restarts with nothing carried."""
        start = date(2017, 3, 1)
        current = self._current_start()
        while start <= current:
            self.Balance.create({
                'employee_id': self.employee.id,
                'leave_type_id': self.annual.id,
                'period_start': start,
                'period_end': start + relativedelta(years=1, days=-1),
                'period_index': start.year - 2016,
                'entitled_days': 24,
            })
            start += relativedelta(years=1)
        manual = self._hire('Ручний вхідний залишок', date(2020, 3, 1))
        self.Balance.create({
            'employee_id': manual.id,
            'leave_type_id': self.annual.id,
            'period_start': date(2020, 3, 1),
            'period_end': date(2021, 2, 28),
            'period_index': 1,
            'entitled_days': 24,
            'carried_over': 3,
        })
        self.assertEqual(self._chain()[-1].carried_over, 24 * (len(self._chain()) - 1))

        path = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                            '20.0.1.1.0', 'post-migration.py')
        spec = importlib.util.spec_from_file_location('l10n_ua_629_mig', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '20.0.1.0.9')
        self.env.invalidate_all()

        chain = self._chain()
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain.period_start, current)
        self.assertEqual(chain.carried_over, 0)
        # A chain opened by hand with its own Carried Over is left alone.
        self.assertEqual(self._chain(manual)[0].period_start, date(2020, 3, 1))
        self.assertEqual(self._chain(manual)[0].carried_over, 3)
