"""Наказ про звільнення і нарахування компенсації — одна кількість днів (#321).

Наказ друкує ціле число днів невикористаної відпустки, а
hr.vacation.balance.calculate_compensation множив середній заробіток на
дробовий залишок: 11,3 дня давали «за 12 календарних днів» у наказі й гроші
за 11,3 дня в розрахунку. Обидва шляхи тепер рахують дні одним хелпером
(l10n_ua_hr_documents.tools.compensable_vacation_days).
"""

import re
from datetime import date
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

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

    def _balance(self, entitled):
        return self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2026,
            'entitled_days': entitled,
        })

    def _order_days(self):
        order = self.env['hr.order'].create({
            'order_type': 'dismissal',
            'date': date(2026, 5, 20),
            'date_dismissal': date(2026, 5, 20),
            'employee_id': self.employee.id,
            'subject': 'Звільнення',
        })
        phrase = order.unused_vacation_days_phrase()
        return int(re.match(r'\d+', phrase).group()) if phrase else 0

    def _compensation(self, balance, **kwargs):
        with patch.object(type(self.env['hr.leave']),
                          '_calculate_average_salary',
                          return_value=AVG_DAILY):
            return balance.calculate_compensation(
                termination_date=date(2026, 5, 20), **kwargs)

    def test_order_and_compensation_use_the_same_day_count(self):
        """Той самий дробовий залишок — однакова кількість днів у наказі й
        у розрахунку компенсації."""
        balance = self._balance(0)
        for entitled, expected in ((11.3, 12), (11.7, 12), (12.0, 12),
                                   (0.4, 1)):
            with self.subTest(entitled=entitled):
                balance.entitled_days = entitled
                self.assertAlmostEqual(balance.remaining_days, entitled)
                order_days = self._order_days()
                self.assertEqual(order_days, expected)
                self.assertEqual(self._compensation(balance),
                                 order_days * AVG_DAILY)

    def test_float_noise_does_not_add_a_day(self):
        """12.000000001 — це 12 днів, а не 13, в обох шляхах."""
        balance = self._balance(12.000000001)
        self.assertEqual(self._order_days(), 12)
        self.assertEqual(self._compensation(balance), 12 * AVG_DAILY)

    def test_without_termination_rounds_the_excess_the_same_way(self):
        """Без звільнення компенсуються лише дні понад 24 — і вони
        округлюються тим самим правилом: 27.3 − 24 = 3.3 → 4 дні."""
        balance = self._balance(51.3)
        balance.used_days = 24
        self.assertAlmostEqual(balance.remaining_days, 27.3)
        self.assertEqual(self._compensation(balance, is_termination=False),
                         4 * AVG_DAILY)

    def test_several_balances_round_the_total_once(self):
        """Дробові залишки кількох видів відпустки: 5,3 + 6,3 = 11,6 → 12 днів
        і в наказі, і в оплаті, а не 6 + 7 = 13 при округленні кожного."""
        other_type = self.env['hr.leave.type'].create({
            'name': 'Additional (#321 rounding test)',
            'is_transferable': False,
        })
        self._balance(5.3)
        self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': other_type.id,
            'year': 2026,
            'entitled_days': 6.3,
        })
        balances = self.env['hr.vacation.balance']._dismissal_balances(
            self.employee, date(2026, 5, 20))
        self.assertEqual(len(balances), 2)
        self.assertEqual(self._order_days(), 12)
        self.assertEqual(balances._compensable_days(), 12)
        self.assertEqual(self._compensation(balances), 12 * AVG_DAILY)

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
