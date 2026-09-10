"""Тести пропорційності неповного робочого часу / суміщення (#149).

Покриття:
- Норма годин версії (scheduled_hours_week/day) масштабується за work_rate
- Норма береться зі штатного календаря версії (resource_calendar_id)
- Суміщення споживає частку штатної одиниці (combined_rate) у розписі
- Валідація combined_rate
"""

from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestWorkRateNorm(ContractTestCase):

    def test_full_rate_norm(self):
        """Повна ставка → 40 год/тиждень, 8 год/день."""
        v = self._create_version(work_rate=1.0)
        self.assertAlmostEqual(v.scheduled_hours_week, 40.0)
        self.assertAlmostEqual(v.scheduled_hours_day, 8.0)

    def test_half_rate_norm(self):
        """0.5 ставки → 20 год/тиждень, 4 год/день."""
        v = self._create_version(work_rate=0.5)
        self.assertAlmostEqual(v.scheduled_hours_week, 20.0)
        self.assertAlmostEqual(v.scheduled_hours_day, 4.0)

    def test_quarter_rate_norm(self):
        v = self._create_version(work_rate=0.25)
        self.assertAlmostEqual(v.scheduled_hours_week, 10.0)
        self.assertAlmostEqual(v.scheduled_hours_day, 2.0)

    def test_norm_from_work_calendar(self):
        """Скорочений графік (36 год) масштабується за ставкою."""
        calendar = self.env.ref(
            'l10n_ua_hr_contract.resource_calendar_ua_std36')
        v = self._create_version(work_rate=0.5,
                                 resource_calendar_id=calendar.id)
        self.assertAlmostEqual(v.scheduled_hours_week, 18.0)
        self.assertAlmostEqual(v.scheduled_hours_day, 3.6)


@tagged('post_install', '-at_install')
class TestCombiningFte(ContractTestCase):

    def _combining(self, **kwargs):
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=20000)
        vals = {
            'employee_id': employee.id,
            'version_id': version.id,
            'combined_job_id': self.job_2.id,
            'combined_department_id': self.department.id,
            'combined_rate': 0.5,
            'date_from': date(2025, 3, 1),
            'surcharge_type': 'percent',
            'surcharge_percent': 50,
            'order_number': 'НК-C09/2025',
            'order_date': date(2025, 2, 25),
        }
        vals.update(kwargs)
        return self.env['hr.job.combining'].create(vals)

    def _staffing_job2(self, units=1.0):
        return self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job_2.id,
            'units': units,
            'salary': 15000.0,
            'date_from': date(2025, 1, 1),
            'state': 'approved',
        })

    def test_combined_rate_default(self):
        jc = self._combining(combined_rate=0.5)
        self.assertAlmostEqual(jc.combined_rate, 0.5)

    def test_combined_rate_validation(self):
        with self.assertRaises(ValidationError):
            self._combining(combined_rate=0.0)
        with self.assertRaises(ValidationError):
            self._combining(combined_rate=1.5)

    def test_combining_consumes_staffing_fraction(self):
        """Активне суміщення споживає combined_rate штатної одиниці job_2."""
        staffing = self._staffing_job2(units=1.0)
        # Посада job_2 без основних працівників → 0 заповнено.
        self.assertAlmostEqual(staffing.filled_units, 0.0)
        self.assertAlmostEqual(staffing.vacant_units, 1.0)

        jc = self._combining(combined_rate=0.5)
        jc.action_activate()
        staffing.invalidate_recordset(['filled_units', 'vacant_units'])
        self.assertAlmostEqual(staffing.filled_units, 0.5)
        self.assertAlmostEqual(staffing.vacant_units, 0.5)

    def test_cancelling_combining_frees_staffing(self):
        """Cancelling frees the unit from the next day, not retroactively.

        `action_cancel` stamps `date_to` = today: the surcharge is paid
        through that day, so the post is held through it too. A cancelled
        record used to drop out of the count at once — and with it out of
        every period the combination genuinely ran.
        """
        staffing = self._staffing_job2(units=1.0)
        jc = self._combining(combined_rate=0.5)
        jc.action_activate()
        jc.action_cancel()
        today = fields.Date.context_today(jc)
        self.assertEqual(jc.date_to, today)

        staffing.invalidate_recordset(['filled_units', 'vacant_units'])
        self.assertAlmostEqual(staffing.filled_units, 0.5)
        self.assertAlmostEqual(staffing.vacant_units, 0.5)

        Staffing = self.env['hr.staffing.table']
        key = (self.company.id, self.department.id, self.job_2.id,
               today + timedelta(days=1))
        self.assertAlmostEqual(Staffing._occupancy_batch([key])[key], 0.0)
