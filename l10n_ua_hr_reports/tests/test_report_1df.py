"""Tests for 1DF report — HR-27 from HR_UKRAINE.md.

Tests cover:
- Report creation
- Name computation
- State workflow (draft -> generated -> submitted)
- Computed totals
- Unique constraint
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReport1DF(TransactionCase):
    """Test hr.report.1df model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Петренко Олександр Миколайович',
            'company_id': cls.company.id,
        })

    def _create_report(self, **kwargs):
        vals = {
            'year': 2025,
            'quarter': '1',
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['hr.report.1df'].create(vals)

    def test_report_creation(self):
        """Report should be created in draft state."""
        report = self._create_report()
        self.assertEqual(report.state, 'draft')

    def test_report_name_computed(self):
        """Name should contain 1DF, year, and quarter."""
        report = self._create_report(year=2025, quarter='1')
        self.assertIn('1ДФ', report.name)
        self.assertIn('2025', report.name)

    def test_report_quarters(self):
        """All 4 quarters should be valid."""
        for q in ['1', '2', '3', '4']:
            report = self._create_report(quarter=q)
            self.assertEqual(report.quarter, q)
            report.unlink()

    def test_report_generate(self):
        """Generate should move to generated state."""
        report = self._create_report()
        report.action_generate()
        self.assertEqual(report.state, 'generated')

    def test_report_submit(self):
        """Submit should move to submitted state."""
        report = self._create_report()
        report.action_generate()
        report.action_submit()
        self.assertEqual(report.state, 'submitted')

    def test_report_draft_reset(self):
        """Draft should reset from generated."""
        report = self._create_report()
        report.action_generate()
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_report_totals_empty(self):
        """Empty report should have zero totals."""
        report = self._create_report()
        self.assertEqual(report.total_employees, 0)
        self.assertEqual(report.total_accrued, 0)
        self.assertEqual(report.total_pdfo, 0)
        self.assertEqual(report.total_military, 0)

    def test_report_unique_constraint(self):
        """Same year + quarter + company should fail."""
        self._create_report(year=2025, quarter='2')
        with self.assertRaises(Exception):
            self._create_report(year=2025, quarter='2')

    def test_report_line_creation(self):
        """Should be able to add report lines."""
        report = self._create_report()
        self.env['hr.report.1df.line'].create({
            'report_id': report.id,
            'employee_id': self.employee.id,
            'rnokpp': '3184710691',
            'accrued_amount': 25000,
            'paid_amount': 25000,
            'pdfo_amount': 4500,
            'military_amount': 1250,
            'income_type': '101',
        })
        self.assertEqual(len(report.line_ids), 1)

    def test_generate_includes_payslips_ending_on_31st(self):
        """A quarter ends on its real last day, not on the 28th: payslips of
        March (ending 31.03) and of the 30-day months belong to the report."""
        from datetime import date
        for month_end in (date(2025, 1, 31), date(2025, 3, 31)):
            slip = self.env['hr.payslip'].create({
                'employee_id': self.employee.id,
                'date_from': month_end.replace(day=1),
                'date_to': month_end,
                'company_id': self.company.id,
            })
            slip.write({'state': 'done'})
        report = self._create_report(year=2025, quarter='1')
        report.action_generate()
        self.assertEqual(report.total_employees, 1)

        q2 = self._create_report(year=2025, quarter='2')
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'company_id': self.company.id,
        })
        slip.write({'state': 'done'})
        q2.action_generate()
        self.assertEqual(q2.total_employees, 1)
