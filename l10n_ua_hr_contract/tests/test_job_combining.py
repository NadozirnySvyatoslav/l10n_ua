"""Tests for job combining (сумісництво) — HR-6 from HR_UKRAINE.md.

Tests cover:
- Job combining creation
- Surcharge calculation (percent and fixed)
- State workflow (draft -> active -> cancelled)
- Allowance creation on activation
"""

from datetime import date

from odoo import fields
from odoo.tests import tagged
from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestJobCombining(ContractTestCase):
    """Test hr.job.combining workflow."""

    def _create_combining(self, employee=None, version=None, **kwargs):
        if employee is None:
            employee = self._create_employee()
        if version is None:
            version = self._create_version(employee=employee, wage=20000)
        vals = {
            'employee_id': employee.id,
            'version_id': version.id,
            'combined_job_id': self.job_2.id,
            'combined_department_id': self.department.id,
            'date_from': date(2025, 3, 1),
            'surcharge_type': 'percent',
            'surcharge_percent': 50,
            'order_number': 'НК-C01/2025',
            'order_date': date(2025, 2, 25),
        }
        vals.update(kwargs)
        return self.env['hr.job.combining'].create(vals)

    def test_combining_creation(self):
        """Job combining should be created in draft state."""
        jc = self._create_combining()
        self.assertEqual(jc.state, 'draft')
        self.assertTrue(jc.name)

    def test_surcharge_percent_calculation(self):
        """Percent surcharge = version.wage * percent / 100."""
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=20000)
        jc = self._create_combining(
            employee=employee, version=version,
            surcharge_type='percent', surcharge_percent=50,
        )
        self.assertAlmostEqual(jc.calculated_surcharge, 10000, places=2)

    def test_surcharge_fixed_calculation(self):
        """Fixed surcharge should use the direct amount."""
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=20000)
        jc = self._create_combining(
            employee=employee, version=version,
            surcharge_type='fixed',
            surcharge_amount=7000,
        )
        self.assertAlmostEqual(jc.calculated_surcharge, 7000, places=2)

    def test_combining_activate(self):
        """Activation should create an allowance on the version."""
        jc = self._create_combining()
        jc.action_activate()
        self.assertEqual(jc.state, 'active')
        self.assertTrue(jc.allowance_id, 'Allowance should be created on activation')

    def test_combining_cancel(self):
        """Cancellation closes the allowance on the same day it closes the
        combination — and that day is still paid.

        The surcharge runs through `date_to` inclusive, so cancelling today
        stops it tomorrow, exactly as the staff unit is freed tomorrow.
        """
        jc = self._create_combining()
        jc.action_activate()
        jc.action_cancel()
        self.assertEqual(jc.state, 'cancelled')
        self.assertEqual(jc.allowance_id.date_to, jc.date_to)
        self.assertTrue(jc.allowance_id.is_active)

    def test_correcting_the_period_moves_the_surcharge_too(self):
        """The surcharge is paid for the period of the combination.

        Payroll reads the allowance, not this model, and the allowance carries
        dates of its own. Left unsynced, correcting `date_to` freed the staff
        unit while the surcharge went on being paid — and every recomputation
        of those months paid it again.
        """
        jc = self._create_combining()
        jc.action_activate()
        jc.action_cancel()

        jc.date_to = date(2025, 6, 30)
        self.assertEqual(jc.allowance_id.date_to, date(2025, 6, 30))
        self.assertFalse(jc.allowance_id.is_active)

        # The start moves too: the order may have been issued for a later day.
        jc.date_from = date(2025, 4, 1)
        self.assertEqual(jc.allowance_id.date_from, date(2025, 4, 1))

    def test_reopening_the_period_revives_the_surcharge(self):
        """Clearing the end date reopens both, not just the staffing unit."""
        jc = self._create_combining()
        jc.action_activate()
        jc.action_cancel()
        jc.date_to = date(2025, 6, 30)
        self.assertFalse(jc.allowance_id.is_active)

        jc.write({'state': 'active', 'date_to': False})
        self.assertFalse(jc.allowance_id.date_to)
        self.assertTrue(jc.allowance_id.is_active)

    def test_correcting_the_rate_moves_the_surcharge_too(self):
        """The percentage the payslip uses is the one on the order.

        The allowance keeps its own copy of the rate. Left unsynced, editing
        the percentage moved `calculated_surcharge` on this form and nothing
        at all on the payslip, because payroll reads the allowance.
        """
        jc = self._create_combining(surcharge_percent=50)
        jc.action_activate()
        self.assertEqual(jc.allowance_id.calculation_method, 'percent_salary')
        self.assertAlmostEqual(jc.allowance_id.percent, 50)

        jc.surcharge_percent = 30
        self.assertAlmostEqual(jc.allowance_id.percent, 30)

    def test_switching_to_a_fixed_surcharge_clears_the_percentage(self):
        """Changing the kind of surcharge swaps both halves of the copy."""
        jc = self._create_combining(surcharge_percent=50)
        jc.action_activate()

        jc.write({'surcharge_type': 'fixed', 'surcharge_amount': 1500})
        self.assertEqual(jc.allowance_id.calculation_method, 'fixed')
        self.assertAlmostEqual(jc.allowance_id.amount, 1500)
        self.assertAlmostEqual(jc.allowance_id.percent, 0)

        jc.write({'surcharge_type': 'percent', 'surcharge_percent': 40})
        self.assertEqual(jc.allowance_id.calculation_method, 'percent_salary')
        self.assertAlmostEqual(jc.allowance_id.percent, 40)
        self.assertAlmostEqual(jc.allowance_id.amount, 0)

    def test_moving_the_combination_moves_the_surcharge(self):
        """The surcharge is paid on the version the combination names."""
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=20000)
        jc = self._create_combining(employee=employee, version=version)
        jc.action_activate()
        self.assertEqual(jc.allowance_id.version_id, version)

        later = self._create_version(employee=employee, wage=25000)
        jc.version_id = later
        self.assertEqual(jc.allowance_id.version_id, later)

    def test_moving_to_another_position_renames_the_surcharge(self):
        jc = self._create_combining()
        jc.action_activate()
        self.assertIn(self.job_2.name, jc.allowance_id.notes)

        jc.combined_job_id = self.job
        self.assertIn(self.job.name, jc.allowance_id.notes)

    def test_cancelled_before_it_started_closes_the_surcharge_for_good(self):
        """A combination that never ran must not come alive on its start date.

        `is_active` is stored and recomputed only from the allowance's own
        dates, so an empty end date on a start still ahead would turn true the
        moment anything rewrote them. The allowance is closed the day before
        it opens instead.
        """
        jc = self._create_combining(date_from=date(2099, 1, 1))
        jc.action_activate()
        jc.action_cancel()

        self.assertFalse(jc.date_to)
        self.assertEqual(jc.allowance_id.date_to, date(2098, 12, 31))
        self.assertFalse(jc.allowance_id.is_active)

    def test_cancellation_is_dated_by_its_own_order(self):
        """The order's date ends the combination, not the day of the click.

        The cancellation order is registered on this same form and is
        routinely dated earlier than the day the officer gets to it. Stamping
        today would hold the staff unit — and go on paying the surcharge — for
        every day in between.
        """
        jc = self._create_combining()
        jc.action_activate()
        jc.cancellation_order_date = date(2025, 6, 30)
        jc.action_cancel()

        self.assertEqual(jc.date_to, date(2025, 6, 30))
        self.assertEqual(jc.allowance_id.date_to, date(2025, 6, 30))

    def test_cancelling_ends_a_planned_period_early(self):
        """A planned end date is no reason to keep paying past the order.

        `date_to` may already carry the day the combination was meant to run
        until. Cancelling before that day cuts the period short — otherwise
        the post would stay occupied, and the surcharge paid, through a period
        an order has already ended.
        """
        jc = self._create_combining(date_to=date(2099, 12, 31))
        jc.action_activate()
        jc.action_cancel()

        today = fields.Date.context_today(jc)
        self.assertEqual(jc.date_to, today)
        self.assertEqual(jc.allowance_id.date_to, today)

    def test_cancelling_a_closed_period_keeps_its_end(self):
        """A cancellation ends a combination early; it never extends one."""
        jc = self._create_combining(date_to=date(2025, 5, 31))
        jc.action_activate()
        jc.action_cancel()

        self.assertEqual(jc.date_to, date(2025, 5, 31))
        self.assertEqual(jc.allowance_id.date_to, date(2025, 5, 31))

    def test_combining_date_validation(self):
        """End date must be after start date."""
        with self.assertRaises(Exception):
            self._create_combining(
                date_from=date(2025, 6, 1),
                date_to=date(2025, 5, 1),
            )

    def test_combining_display_name(self):
        """Display name should contain employee and job info."""
        jc = self._create_combining()
        self.assertTrue(jc.display_name)


@tagged('post_install', '-at_install')
class TestJobCombiningMultiCompany(ContractTestCase):
    """Multi-company isolation для hr.job.combining."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Company B'})
        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Dept B', 'company_id': cls.company_b.id,
        })
        cls.job_b = cls.env['hr.job'].create({
            'name': 'Job B', 'department_id': cls.dept_b.id,
            'company_id': cls.company_b.id,
        })

    def test_onchange_version_resets_cross_company_combined(self):
        """Зміна version_id скидає combined_*_id якщо з іншої компанії."""
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=10000)
        # company_id is related from version.company_id → company_a (env.company)

        combining = self.env['hr.job.combining'].new({
            'employee_id': employee.id,
            'version_id': version.id,
            'combined_job_id': self.job_b.id,  # from company B
            'combined_department_id': self.dept_b.id,  # from company B
            'date_from': date(2026, 4, 1),
            'surcharge_type': 'percent',
            'surcharge_percent': 25.0,
        })
        combining._onchange_version_id_reset_combined()
        self.assertFalse(combining.combined_job_id)
        self.assertFalse(combining.combined_department_id)

    def test_onchange_version_keeps_same_company_combined(self):
        employee = self._create_employee()
        version = self._create_version(employee=employee, wage=10000)
        combining = self.env['hr.job.combining'].new({
            'employee_id': employee.id,
            'version_id': version.id,
            'combined_job_id': self.job_2.id,
            'combined_department_id': self.department.id,
            'date_from': date(2026, 4, 1),
            'surcharge_type': 'percent',
            'surcharge_percent': 25.0,
        })
        combining._onchange_version_id_reset_combined()
        self.assertEqual(combining.combined_job_id, self.job_2)
        self.assertEqual(combining.combined_department_id, self.department)
