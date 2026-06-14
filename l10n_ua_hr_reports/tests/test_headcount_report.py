"""Tests for Average Headcount report (hr.report.headcount).

Covers review feedback on PR headcount-report-fix:
- Multi-version employees are counted once per day (dedup by employee_id).
- Dismissal day itself is excluded; day before is counted; day after — not.

This test does NOT depend on hr.order (which lives in l10n_ua_hr_documents);
the "dismissed" state is simulated by writing contract_date_end on all
versions directly — same side-effect that _apply_dismissal produces.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHeadcountReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Тестовий Співробітник',
            'company_id': cls.company.id,
        })
        v0 = cls.employee.with_context(active_test=False).version_ids[:1]
        v0.write({
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
        })
        # Second version (promotion / salary change) — same employment period.
        cls.employee.create_version({'date_version': date(2025, 6, 1)})

        cls.report = cls.env['hr.report.headcount'].create({
            'year': 2026,
            'month': '3',
            'company_id': cls.company.id,
        })

    def _dismiss(self, dismissal_date):
        """Simulate the side-effect of a confirmed dismissal order."""
        versions = self.employee.with_context(active_test=False).version_ids
        versions.write({'contract_date_end': dismissal_date})
        self.employee.active = False

    def test_multiversion_employee_counted_once(self):
        """Employee with ≥2 versions on the same day must be counted once."""
        versions = self.employee.with_context(active_test=False).version_ids
        self.assertGreaterEqual(len(versions), 2)

        headcount, fte = self.report._count_employees_on_date(date(2026, 1, 15))
        self.assertEqual(headcount, 1,
                         "Multi-version employee must be counted exactly once")
        self.assertEqual(fte, 1.0)

    def test_report_excludes_dismissed_employee(self):
        """Dismissal day NOT counted; day before — counted; day after — not."""
        self._dismiss(date(2026, 3, 15))

        h_before, _ = self.report._count_employees_on_date(date(2026, 3, 14))
        h_dismissal, _ = self.report._count_employees_on_date(date(2026, 3, 15))
        h_after, _ = self.report._count_employees_on_date(date(2026, 3, 16))

        self.assertEqual(h_before, 1, "Day before dismissal must count employee")
        self.assertEqual(h_dismissal, 0, "Dismissal day must NOT count employee")
        self.assertEqual(h_after, 0, "Day after dismissal must NOT count employee")

    def test_archived_employee_still_counted_for_past_periods(self):
        """Archived (dismissed) employee must remain in past reports."""
        self._dismiss(date(2026, 3, 15))
        # Previous month — employee was actively employed.
        prev_report = self.env['hr.report.headcount'].create({
            'year': 2026,
            'month': '2',
            'company_id': self.company.id,
        })
        h, _ = prev_report._count_employees_on_date(date(2026, 2, 10))
        self.assertEqual(h, 1,
                         "Archived employee must still be counted before dismissal date")

    # --- review for re-hire scenario --------------------------------------

    def test_archived_without_termination_data_excluded(self):
        """Archived employee with no contract_date_end and no departure_date
        is excluded conservatively (data-error safety net)."""
        # Simulate broken state: just archive, no termination dates anywhere.
        self.employee.active = False
        if 'departure_date' in self.employee._fields:
            self.employee.departure_date = False
        versions = self.employee.with_context(active_test=False).version_ids
        versions.write({'contract_date_end': False})

        h, _ = self.report._count_employees_on_date(date(2026, 3, 10))
        self.assertEqual(h, 0,
                         "Archived employee with no termination date must "
                         "be excluded conservatively")

    def test_archived_with_departure_date_only(self):
        """Archived employee with departure_date but no contract_date_end
        (Odoo's standard departure wizard) — departure_date wins as fallback."""
        if 'departure_date' not in self.employee._fields:
            self.skipTest("departure_date not available on hr.employee")
        # Simulate standard Odoo departure wizard: archive + departure_date only.
        self.employee.active = False
        self.employee.departure_date = date(2026, 3, 15)
        versions = self.employee.with_context(active_test=False).version_ids
        versions.write({'contract_date_end': False})

        # Day before departure: counted.
        h_before, _ = self.report._count_employees_on_date(date(2026, 3, 14))
        self.assertEqual(h_before, 1)
        # Departure day: NOT counted.
        h_dep, _ = self.report._count_employees_on_date(date(2026, 3, 15))
        self.assertEqual(h_dep, 0)
        # Day after: NOT counted.
        h_after, _ = self.report._count_employees_on_date(date(2026, 3, 16))
        self.assertEqual(h_after, 0)
