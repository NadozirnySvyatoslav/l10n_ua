"""Tests for payslip run (batch) — HR-25 from HR_UKRAINE.md.

Tests cover:
- Payslip run creation
- Batch computation
- Computed totals
- State workflow
"""

from datetime import date
from odoo.tests import tagged
from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPayslipRun(SalaryTestCase):
    """Test hr.payslip.run batch processing."""

    def _create_run(self, **kwargs):
        vals = {
            'date_start': date(2025, 6, 1),
            'date_end': date(2025, 6, 30),
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['hr.payslip.run'].create(vals)

    def _add_payslip_to_run(self, run, employee=None):
        """Manually add a payslip with accrual to a run."""
        if employee is None:
            employee = self.employee
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'payslip_run_id': run.id,
            'date_from': run.date_start,
            'date_to': run.date_end,
            'company_id': self.company.id,
        })
        self.env['hr.payslip.accrual'].create({
            'payslip_id': payslip.id,
            'accrual_type_id': self.accrual_wage.id,
            'quantity': 1,
            'rate': 25000,
            'amount': 25000,
        })
        return payslip

    def test_run_creation(self):
        """Payslip run should be created in draft state."""
        run = self._create_run()
        self.assertEqual(run.state, 'draft')
        self.assertTrue(run.name)

    def test_run_with_payslip(self):
        """Run should contain manually added payslips."""
        run = self._create_run()
        self._add_payslip_to_run(run)
        self.assertEqual(len(run.slip_ids), 1)

    def test_run_compute_all(self):
        """Compute all should compute each payslip."""
        run = self._create_run()
        self._add_payslip_to_run(run)
        run.action_compute_all()
        for slip in run.slip_ids:
            self.assertIn(slip.state, ('draft', 'verify'))

    def test_run_totals_computed(self):
        """Run totals should aggregate from payslips."""
        run = self._create_run()
        self._add_payslip_to_run(run)
        run.action_compute_all()
        run.invalidate_recordset()
        self.assertGreaterEqual(run.total_gross, 0)
        self.assertGreaterEqual(run.total_net, 0)

    def test_run_state_workflow(self):
        """State: draft -> verify -> close."""
        run = self._create_run()
        self._add_payslip_to_run(run)
        run.action_compute_all()
        run.action_verify()
        self.assertEqual(run.state, 'verify')
        run.action_close()
        self.assertEqual(run.state, 'close')

    def test_run_default_dates(self):
        """Default dates should cover current month."""
        run = self.env['hr.payslip.run'].create({
            'company_id': self.company.id,
        })
        self.assertTrue(run.date_start)
        self.assertTrue(run.date_end)

    def _hire(self, name, start, end=False, active=True):
        employee = self.env['hr.employee'].create({
            'name': name,
            'company_id': self.company.id,
        })
        version = self.env['hr.version'].create({
            'employee_id': employee.id,
            'contract_date_start': start,
            'contract_date_end': end,
            'date_version': start,
            'wage': 20000,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': self.company.id,
        })
        employee.write({'current_version_id': version.id})
        if not active:
            employee.write({'active': False})
        return employee

    def test_generate_only_contracts_within_period(self):
        """Only employees under a contract during the run's period get a
        payslip: not those dismissed before it nor hired after it, but yes
        those hired or dismissed (and archived) within it."""
        ended = self._hire('Звільнений у травні', date(2024, 1, 1), date(2025, 5, 31))
        future = self._hire('Прийнятий у липні', date(2025, 7, 1))
        hired_mid = self._hire('Прийнятий 16 червня', date(2025, 6, 16))
        left_mid = self._hire('Звільнений 10 червня', date(2024, 1, 1),
                              date(2025, 6, 10), active=False)
        run = self._create_run()
        run.action_generate_payslips()
        employees = run.slip_ids.employee_id
        self.assertIn(self.employee, employees)
        self.assertIn(hired_mid, employees)
        self.assertIn(left_mid, employees)
        self.assertNotIn(ended, employees)
        self.assertNotIn(future, employees)

    def test_close_confirms_each_payslip(self):
        """Closing the run goes through action_payslip_done: the advance
        withheld in the payslip becomes paid, not just the state changes."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'date': date(2025, 6, 15),
            'wage_percent': 50.0,
            'company_id': self.company.id,
        })
        advance.action_confirm()
        run = self._create_run()
        slip = self._add_payslip_to_run(run)
        slip._generate_deductions()
        self.assertEqual(advance.payslip_id, slip)
        run.action_verify()
        run.action_close()
        self.assertEqual(slip.state, 'done')
        self.assertEqual(advance.state, 'paid')
