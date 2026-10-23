"""Наказ про звільнення і нарахування компенсації — одна кількість днів (#321).

Наказ друкує ціле число днів невикористаної відпустки, а
hr.vacation.balance.calculate_compensation множив середній заробіток на
дробовий залишок: 11,3 дня давали «за 12 календарних днів» у наказі й гроші
за 11,3 дня в розрахунку. Обидва шляхи тепер рахують дні одним хелпером
(l10n_ua_hr_documents.tools.compensable_vacation_days).

On dismissal both the order and the payment take the days from
hr.vacation.entitlement (pro-rated to the time worked); without dismissal the
payment takes the days above the annual minimum from the balances.
"""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_hr_documents.tools import compensable_vacation_days

AVG_DAILY = 1000.0


@tagged('post_install', '-at_install')
class TestVacationCompensationRounding(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Звільнюваний Працівник #321',
            'company_id': cls.env.company.id,
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Annual Basic (#321 rounding test)',
            'is_transferable': False,
            'annual_days': 24,
        })
        # Public holidays are working days under martial law.
        cls.env['resource.calendar.leaves'].search([('resource_id', '=', False)]).unlink()
        cls.basic = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.additional = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_additional')
        cls.hired = cls.env['hr.employee'].create({
            'name': 'Dismissed Employee with a hire date (#321)',
            'company_id': cls.env.company.id,
            'hire_date': date(2026, 3, 1),
        })
        for leave_type, norm in ((cls.basic, 24), (cls.additional, 7)):
            cls.env['hr.vacation.balance'].create({
                'employee_id': cls.hired.id,
                'leave_type_id': leave_type.id,
                'period_start': date(2026, 3, 1),
                'period_end': date(2027, 2, 28),
                'entitled_days': norm,
            })

    def _balance(self, entitled):
        return self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2026,
            'entitled_days': entitled,
        })

    def _compensation(self, balance, termination_date=date(2026, 5, 20), **kwargs):
        with patch.object(type(self.env['hr.leave']),
                          '_calculate_average_salary',
                          return_value=AVG_DAILY):
            return balance.calculate_compensation(
                termination_date=termination_date, **kwargs)

    def _order_days(self, employee, dismissal_date):
        order = self.env['hr.order'].create({
            'order_type': 'dismissal',
            'date': dismissal_date,
            'date_dismissal': dismissal_date,
            'employee_id': employee.id,
            'subject': 'Dismissal',
        })
        phrase = order.unused_vacation_days_phrase()
        return int(phrase.split()[0]) if phrase else 0

    def test_order_and_compensation_use_the_same_day_count(self):
        """On dismissal the order and the payment count the same days: the
        days the order quotes times the average salary are the compensation,
        for any balance the payment is started from."""
        balance = self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.hired.id),
            ('leave_type_id', '=', self.basic.id),
        ])
        # 6 days: 0.39 + 0.12 = 0.51 -> 1; 21 days: 1.38 + 0.40 = 1.78 -> 2;
        # 200 days: 13.15 + 3.84 = 16.99 -> 17.
        for dismissal_date, expected in ((date(2026, 3, 6), 1),
                                         (date(2026, 3, 21), 2),
                                         (date(2026, 9, 16), 17)):
            with self.subTest(dismissal_date=dismissal_date):
                order_days = self._order_days(self.hired, dismissal_date)
                self.assertEqual(order_days, expected)
                self.assertEqual(self._compensation(balance, dismissal_date),
                                 order_days * AVG_DAILY)

    def test_float_noise_does_not_add_a_day(self):
        """12.000000001 — це 12 днів, а не 13."""
        self.assertEqual(compensable_vacation_days(12.000000001), 12)
        self.assertEqual(compensable_vacation_days(11.3), 12)
        self.assertEqual(compensable_vacation_days(0.4), 1)

    def test_without_termination_pays_the_rest_once_the_minimum_is_used(self):
        """Without dismissal, once 24 days have been used, the rest of the
        leave is paid out, rounded by the same rule: 51.3 − 24 used = 27.3
        remaining -> 28 days. The 24 days are not taken off a second time."""
        balance = self._balance(51.3)
        balance.used_days = 24
        self.assertAlmostEqual(balance.remaining_days, 27.3)
        self.assertEqual(self._compensation(balance, is_termination=False),
                         28 * AVG_DAILY)

    def test_without_termination_pays_nothing_before_the_minimum_is_used(self):
        """Without dismissal nothing is paid out until 24 days are used."""
        balance = self._balance(31)
        balance.used_days = 20
        self.assertEqual(self._compensation(balance, is_termination=False), 0)

    def test_several_leave_types_round_the_total_once(self):
        """Fractional days of several leave types are rounded once in total:
        1.38 basic + 0.40 additional = 1.78 -> 2 days paid for, not 2 + 1 = 3
        from rounding each up."""
        balances = self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.hired.id)])
        self.assertEqual(balances._compensable_days(termination_date=date(2026, 3, 21)), 2)
        self.assertEqual(self._compensation(balances, date(2026, 3, 21)), 2 * AVG_DAILY)

    def test_balances_of_different_employees_are_refused(self):
        """Середній заробіток — свій у кожного працівника, тож одна сума на
        кількох працівників не рахується."""
        other = self.env['hr.employee'].create({
            'name': 'Інший Працівник #321',
            'company_id': self.env.company.id,
        })
        balances = self._balance(3) | self.env['hr.vacation.balance'].create({
            'employee_id': other.id,
            'leave_type_id': self.leave_type.id,
            'year': 2026,
            'entitled_days': 3,
        })
        with self.assertRaises(ValidationError):
            self._compensation(balances)
