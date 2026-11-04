"""Amounts for a period in the averages (#416).

Порядок № 100, п. 3, абз. 3: a bonus for a quarter, half-year or year counts
spread over its months, counting back from the month it was accrued in, pro
rata to the working days worked. A recalculation counts in the month it
corrects (п. 3, абз. 2). Порядок № 1266, п. 4: the sick-leave average is
capped by the maximum contribution base per calendar day.

The calculation period of these tests is July 2025 – June 2026.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PERIOD = (date(2025, 7, 1), date(2026, 6, 30))


@tagged('post_install', '-at_install')
class TestAveragePeriodAmounts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Average Period Employee', 'company_id': cls.company.id})

    def setUp(self):
        super().setUp()
        if 'hr.payslip' not in self.env:
            self.skipTest('l10n_ua_hr_salary is not installed')

    def _payslip(self, month, lines, worked_days=0):
        """A closed payslip of the month with [(code, amount)]."""
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': month,
            'date_to': month + relativedelta(months=1, days=-1),
        })
        for code, amount in lines:
            kind = self.env['hr.accrual.type'].search([('code', '=', code)], limit=1)
            self.env['hr.payslip.accrual'].create({
                'payslip_id': slip.id, 'accrual_type_id': kind.id,
                'quantity': 1, 'rate': amount, 'amount': amount,
            })
        slip.write({'state': 'done', 'worked_days': worked_days})
        return slip

    def _earnings(self):
        Payslip = self.env['hr.payslip']
        payslips = Payslip.search([
            ('employee_id', '=', self.employee.id), ('state', '=', 'done'),
            ('date_from', '>=', PERIOD[0]), ('date_to', '<=', PERIOD[1])])
        return self.env['hr.leave']._l10n_ua_vacation_earnings(
            self.employee, payslips, *PERIOD)[0]

    # Bonuses

    def test_types_shipped(self):
        months = {t.code: t.l10n_ua_bonus_months for t in self.env['hr.accrual.type'].search(
            [('code', 'in', ('BONUS', 'BONUS_Q', 'BONUS_H', 'BONUS_Y'))])}
        self.assertEqual(months, {'BONUS': '1', 'BONUS_Q': '3', 'BONUS_H': '6', 'BONUS_Y': '12'})

    def test_quarterly_bonus_at_the_start_counts_its_share(self):
        # Accrued in July 2025 for May–July: only July is in the period.
        self._payslip(date(2025, 5, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2025, 6, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2025, 7, 1), [('SALARY', 10000), ('BONUS_Q', 9000)], worked_days=20)
        self.assertAlmostEqual(self._earnings(), 10000 + 9000 * 20 / 60, places=2)

    def test_quarterly_bonus_inside_counts_whole(self):
        for month in (1, 2, 3):
            self._payslip(date(2026, month, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2026, 3, 1), [('BONUS_Q', 6000)], worked_days=0)
        self.assertAlmostEqual(self._earnings(), 30000 + 6000, places=2)

    def test_share_follows_days_worked(self):
        # May 10 days, June 20, July 30 days worked: July gets half.
        self._payslip(date(2025, 5, 1), [('SALARY', 5000)], worked_days=10)
        self._payslip(date(2025, 6, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2025, 7, 1), [('SALARY', 15000), ('BONUS_Q', 12000)], worked_days=30)
        self.assertAlmostEqual(self._earnings(), 15000 + 6000, places=2)

    def test_bonus_for_an_earlier_period_divides_by_its_days(self):
        # A bonus for April–June accrued in July (period ending in June): the
        # days of April–June divide it; the months counted are May–July.
        self._payslip(date(2025, 4, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2025, 5, 1), [('SALARY', 10000)], worked_days=20)
        self._payslip(date(2025, 6, 1), [('SALARY', 10000)], worked_days=20)
        july = self._payslip(date(2025, 7, 1), [('SALARY', 10000)], worked_days=20)
        bonus = self.env['hr.payslip.accrual'].create({
            'payslip_id': july.id,
            'accrual_type_id': self.env['hr.accrual.type'].search(
                [('code', '=', 'BONUS_Q')], limit=1).id,
            'quantity': 1, 'rate': 9000, 'amount': 9000,
            'l10n_ua_bonus_period_to': date(2025, 6, 1),
        })
        self.assertTrue(bonus)
        self.assertAlmostEqual(self._earnings(), 10000 + 9000 * 20 / 60, places=2)

    def test_days_unknown_spread_evenly(self):
        self._payslip(date(2025, 7, 1), [('SALARY', 10000), ('BONUS_Y', 12000)])
        # A year back from July 2025: only July is in the period.
        self.assertAlmostEqual(self._earnings(), 10000 + 1000, places=2)

    def test_monthly_bonus_whole(self):
        self._payslip(date(2025, 7, 1), [('SALARY', 10000), ('BONUS', 3000)], worked_days=20)
        self.assertAlmostEqual(self._earnings(), 13000, places=2)

    # Recalculations

    def _retro(self, source, target, amount):
        line = self.env['hr.payslip.accrual'].create({
            'payslip_id': target.id,
            'accrual_type_id': self.env['hr.accrual.type'].search(
                [('code', '=', 'RETRO')], limit=1).id,
            'quantity': 1, 'rate': amount, 'amount': amount,
        })
        self.env['hr.payslip.retro'].create({
            'source_payslip_id': source.id, 'target_payslip_id': target.id,
            'accrual_line_id': line.id, 'old_gross': 0, 'new_gross': amount,
            'gross_delta': amount,
        })

    def test_retro_for_a_month_before_the_period_left_out(self):
        june = self._payslip(date(2025, 6, 1), [('SALARY', 10000)])
        august = self._payslip(date(2025, 8, 1), [('SALARY', 10000)])
        self._retro(june, august, 2000)
        self.assertAlmostEqual(self._earnings(), 10000, places=2)

    def test_retro_after_the_period_for_its_month_added(self):
        may = self._payslip(date(2026, 5, 1), [('SALARY', 10000)])
        july = self._payslip(date(2026, 7, 1), [('SALARY', 10000)])
        self._retro(may, july, 1500)
        self.assertAlmostEqual(self._earnings(), 11500, places=2)

    def test_retro_inside_the_period_counts(self):
        march = self._payslip(date(2026, 3, 1), [('SALARY', 10000)])
        april = self._payslip(date(2026, 4, 1), [('SALARY', 10000)])
        self._retro(march, april, 700)
        self.assertAlmostEqual(self._earnings(), 20700, places=2)

    # Sick leave cap

    def test_sick_average_capped(self):
        params = self.env['hr.psp.parameters'].get_parameters(
            date(2026, 5, 31), self.company.id)
        if not params or not params.max_esv_base:
            self.skipTest('no contribution parameters for 2026')
        for month in range(6, 13):
            self._payslip(date(2025, month, 1), [('SALARY', 1000000)])
        for month in range(1, 6):
            self._payslip(date(2026, month, 1), [('SALARY', 1000000)])
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 10), 'date_to': date(2026, 6, 14),
        })
        cap = round(params.max_esv_base / 30.44, 2)
        self.assertGreater(sick._calculate_average_salary_uncapped(), cap)
        self.assertEqual(sick._calculate_average_salary(), cap)

    def test_sick_average_below_cap_unchanged(self):
        self._payslip(date(2026, 5, 1), [('SALARY', 15000)])
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 10), 'date_to': date(2026, 6, 14),
        })
        self.assertEqual(sick._calculate_average_salary(),
                         sick._calculate_average_salary_uncapped())
