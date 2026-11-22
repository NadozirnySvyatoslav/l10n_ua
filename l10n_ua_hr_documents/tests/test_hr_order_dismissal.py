"""Tests for dismissal-order side effects on employee + versions.

Covers review feedback on PR headcount-report-fix:
- Multi-version employees: contract_date_end is written to ALL versions.
- Cancellation: contract_date_end / termination_order_* / departure_date /
  active are all restored to their pre-apply values.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrOrderDismissal(TransactionCase):

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
        # Add a second version (e.g., promotion on 2025-06-01).
        cls.employee.create_version({'date_version': date(2025, 6, 1)})

    def _make_dismissal(self, dismissal_date, date_order=None):
        return self.env['hr.order'].create({
            'order_type': 'dismissal',
            'date': date_order or dismissal_date,
            'date_dismissal': dismissal_date,
            'employee_id': self.employee.id,
            'subject': 'Test dismissal',
        })

    def test_dismissal_closes_all_versions(self):
        """Every hr.version of the employee must get contract_date_end set."""
        versions = self.employee.with_context(active_test=False).version_ids
        self.assertGreaterEqual(len(versions), 2,
                                "Pre-condition: employee should have ≥2 versions")

        order = self._make_dismissal(date(2026, 3, 15))
        order.action_confirm()

        versions = self.employee.with_context(active_test=False).version_ids
        for v in versions:
            self.assertEqual(v.contract_date_end, date(2026, 3, 15),
                             f"version id={v.id} kept contract_date_end={v.contract_date_end}")
            self.assertEqual(v.termination_order_number, order.name)
            self.assertEqual(v.termination_order_date, order.date)
        self.assertFalse(self.employee.active)
        # Read from the database, not from the cache the assignment filled:
        # in Odoo 20 departure_date lives on hr.employee.departure.
        self.env.invalidate_all()
        employee = self.employee.with_context(active_test=False)
        self.assertEqual(employee.departure_date, date(2026, 3, 15))
        self.assertEqual(order.departure_id, employee.departure_id)
        self.assertTrue(order.departure_id.apply_date)

    def test_cancel_restores_everything(self):
        """action_cancel must restore versions, departure_date and archive state."""
        order = self._make_dismissal(date(2026, 3, 15))
        order.action_confirm()
        order.action_cancel()

        versions = self.employee.with_context(active_test=False).version_ids
        for v in versions:
            self.assertFalse(v.contract_date_end,
                             f"version id={v.id} kept contract_date_end after cancel")
            self.assertFalse(v.termination_order_number)
            self.assertFalse(v.termination_order_date)
        self.assertTrue(self.employee.with_context(active_test=False).active,
                        "Employee must be unarchived after cancel")
        # The employee had no departure before the order: the one the order
        # created is gone again, and so is the departure date.
        self.env.invalidate_all()
        employee = self.employee.with_context(active_test=False)
        self.assertFalse(employee.departure_id)
        self.assertFalse(employee.departure_date)
        self.assertFalse(order.departure_id)
