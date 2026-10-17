"""Tests for timesheet (табель) — HR-17 from HR_UKRAINE.md.

Tests cover:
- Timesheet creation
- Name computation
- State workflow (draft -> confirmed -> approved)
- Timesheet code reference data
- Unique constraint
"""

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestTimesheetCode(TransactionCase):
    """Test hr.timesheet.code reference data."""

    def _create_code(self, **kwargs):
        vals = {
            'name': 'Робочий день',
            'code': 'TST',
            'code_type': 'work',
            'is_worked': True,
            'default_hours': 8.0,
        }
        vals.update(kwargs)
        return self.env['hr.timesheet.code'].create(vals)

    def test_code_creation(self):
        """Timesheet code should have required fields."""
        code = self._create_code()
        self.assertEqual(code.code, 'TST')
        self.assertEqual(code.code_type, 'work')
        self.assertTrue(code.is_worked)

    def test_code_types(self):
        """All code types should be valid."""
        for i, ctype in enumerate(['work', 'absence', 'leave', 'sick', 'holiday', 'other']):
            code = self._create_code(
                name=f'Code {ctype}',
                code=f'T{i:02d}',
                code_type=ctype,
            )
            self.assertEqual(code.code_type, ctype)
            code.unlink()

    def test_code_unique_constraint(self):
        """Code should be unique."""
        self._create_code(code='UNQ')
        # A database constraint: it fires at flush and aborts the transaction.
        # The savepoint keeps the transaction usable, the flush raises the
        # error inside the block, and mute_logger silences the expected
        # "bad query" line.
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            self._create_code(code='UNQ', name='Duplicate')
            self.env.flush_all()


@tagged('post_install', '-at_install')
class TestTimesheet(TransactionCase):
    """Test hr.timesheet model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.department = cls.env['hr.department'].create({
            'name': 'Бухгалтерія',
            'company_id': cls.company.id,
        })

    def _create_timesheet(self, **kwargs):
        vals = {
            'year': 2025,
            'month': '6',
            'department_id': self.department.id,
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['hr.timesheet'].create(vals)

    def test_timesheet_creation(self):
        """Timesheet should be created in draft state."""
        ts = self._create_timesheet()
        self.assertEqual(ts.state, 'draft')

    def test_timesheet_name_computed(self):
        """Name should contain month, year, and department."""
        ts = self._create_timesheet(month='6', year=2025)
        self.assertIn('2025', ts.name)
        self.assertIn('Бухгалтерія', ts.name)

    def test_timesheet_confirm(self):
        """Confirm should set state to confirmed."""
        ts = self._create_timesheet()
        ts.action_confirm()
        self.assertEqual(ts.state, 'confirmed')

    def test_timesheet_approve(self):
        """Approve should set state to approved."""
        ts = self._create_timesheet()
        ts.action_confirm()
        ts.action_approve()
        self.assertEqual(ts.state, 'approved')

    def test_timesheet_draft_reset(self):
        """Draft should reset from confirmed."""
        ts = self._create_timesheet()
        ts.action_confirm()
        ts.action_draft()
        self.assertEqual(ts.state, 'draft')

    def test_timesheet_unique_constraint(self):
        """Same year + month + department + company should fail."""
        self._create_timesheet()
        # A database constraint: it fires at flush and aborts the transaction.
        # The savepoint keeps the transaction usable, the flush raises the
        # error inside the block, and mute_logger silences the expected
        # "bad query" line.
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            self._create_timesheet()
            self.env.flush_all()

    def test_timesheet_different_months(self):
        """Different months should be allowed."""
        ts1 = self._create_timesheet(month='6')
        ts2 = self._create_timesheet(month='7')
        self.assertNotEqual(ts1.id, ts2.id)

    def test_timesheet_totals_empty(self):
        """Empty timesheet should have zero totals."""
        ts = self._create_timesheet()
        self.assertEqual(ts.total_employees, 0)
        self.assertEqual(ts.total_worked_days, 0)
        self.assertEqual(ts.total_worked_hours, 0)


@tagged('post_install', '-at_install')
class TestTimesheetMultiCompany(TransactionCase):
    """Multi-company isolation для hr.timesheet."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Company B'})
        cls.dept_a = cls.env['hr.department'].create({
            'name': 'Dept A', 'company_id': cls.company_a.id,
        })
        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Dept B', 'company_id': cls.company_b.id,
        })

    def test_onchange_company_resets_foreign_department(self):
        ts = self.env['hr.timesheet'].new({
            'year': 2026, 'month': '4',
            'company_id': self.company_a.id,
            'department_id': self.dept_a.id,
        })
        ts.company_id = self.company_b
        ts._onchange_company_id()
        self.assertFalse(ts.department_id)

    def test_onchange_company_keeps_same_company_department(self):
        ts = self.env['hr.timesheet'].new({
            'year': 2026, 'month': '4',
            'company_id': self.company_a.id,
            'department_id': self.dept_a.id,
        })
        # та сама компанія — нічого не скидається
        ts._onchange_company_id()
        self.assertEqual(ts.department_id, self.dept_a)
