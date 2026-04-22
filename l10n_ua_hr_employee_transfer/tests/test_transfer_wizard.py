"""Tests for hr.employee.transfer.wizard — issue #32."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestEmployeeTransfer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Transfer Target Co'})
        cls.env.user.write({'company_ids': [(4, cls.company_b.id)]})

        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Target Dept', 'company_id': cls.company_b.id,
        })
        cls.job_b = cls.env['hr.job'].create({
            'name': 'Target Job', 'company_id': cls.company_b.id,
        })

        cls.source_employee = cls.env['hr.employee'].with_company(cls.company_a).create({
            'name': 'Іван Петренко',
            'company_id': cls.company_a.id,
            'rnokpp': '1234567899',
        })

    def _make_wizard(self, **overrides):
        vals = {
            'source_employee_id': self.source_employee.id,
            'source_company_id': self.company_a.id,
            'target_company_id': self.company_b.id,
            'dismissal_date': date(2026, 4, 30),
            'hire_date': date(2026, 5, 1),
            'new_department_id': self.dept_b.id,
            'new_job_id': self.job_b.id,
        }
        vals.update(overrides)
        return self.env['hr.employee.transfer.wizard'].create(vals)

    def test_transfer_creates_new_employee(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        self.assertTrue(new_employee)
        self.assertEqual(new_employee.company_id, self.company_b)
        self.assertEqual(new_employee.name, 'Іван Петренко')
        self.assertEqual(new_employee.rnokpp, '1234567899')
        self.assertEqual(new_employee.previous_employee_id, self.source_employee)

    def test_transfer_deactivates_source(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        self.source_employee.invalidate_recordset(['active'])
        self.assertFalse(self.source_employee.active)

    def test_transfer_creates_hr_orders(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id

        dismissal_orders = self.env['hr.order'].search([
            ('employee_id', '=', self.source_employee.id),
            ('order_type', '=', 'dismissal'),
        ])
        self.assertTrue(dismissal_orders, 'Dismissal hr.order must be created')
        self.assertEqual(dismissal_orders.date_dismissal, date(2026, 4, 30))

        hiring_orders = self.env['hr.order'].search([
            ('employee_id', '=', new_employee.id),
            ('order_type', '=', 'hiring'),
        ])
        self.assertTrue(hiring_orders, 'Hiring hr.order must be created')
        self.assertEqual(hiring_orders.date_start, date(2026, 5, 1))

    def test_cannot_transfer_to_same_company(self):
        with self.assertRaises(UserError):
            self._make_wizard(target_company_id=self.company_a.id)

    def test_cannot_transfer_twice(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        with self.assertRaises(UserError):
            wizard.action_transfer()

    def test_hire_date_autocomputed(self):
        wizard = self.env['hr.employee.transfer.wizard'].create({
            'source_employee_id': self.source_employee.id,
            'source_company_id': self.company_a.id,
            'target_company_id': self.company_b.id,
            'dismissal_date': date(2026, 4, 30),
        })
        self.assertEqual(wizard.hire_date, date(2026, 5, 1))

    def test_hire_before_dismissal_rejected(self):
        with self.assertRaises(UserError):
            self._make_wizard(hire_date=date(2026, 4, 29))

    def test_vacation_reset_is_default(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard.vacation_transfer_mode, 'reset')
