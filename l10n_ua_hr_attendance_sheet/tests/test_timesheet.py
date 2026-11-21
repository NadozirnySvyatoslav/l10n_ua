"""Tests for timesheet (табель) — HR-17 from HR_UKRAINE.md.

Tests cover:
- Timesheet creation
- Name computation
- State workflow (draft -> confirmed -> approved)
- Timesheet code reference data
- Unique constraint
"""

from odoo.tests import TransactionCase, tagged


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
        with self.assertRaises(Exception):
            self._create_code(code='UNQ', name='Duplicate')


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
        with self.assertRaises(Exception):
            self._create_timesheet()

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


@tagged('post_install', '-at_install')
class TestTimesheetNorm(TransactionCase):
    """The month's norm is its working days; worked days are those worked.

    June 2025 has 21 working days (Mon–Fri, no production calendar).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from datetime import date
        cls.date = date
        cls.company = cls.env.company
        cls.department = cls.env['hr.department'].create({
            'name': 'Цех (норма табеля)', 'company_id': cls.company.id,
        })
        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_TS_NORM_1',
            'name': 'Щорічна (табель)',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
        })

    def _employee(self, name, start=None, end=False, active=True):
        employee = self.env['hr.employee'].create({
            'name': name,
            'company_id': self.company.id,
            'department_id': self.department.id,
        })
        if start:
            version = self.env['hr.version'].create({
                'employee_id': employee.id,
                'contract_date_start': start,
                'contract_date_end': end,
                'date_version': start,
                'company_id': self.company.id,
                'department_id': self.department.id,
            })
            employee.write({'current_version_id': version.id})
        if not active:
            employee.write({'active': False})
        return employee

    def _generate(self):
        sheet = self.env['hr.timesheet'].create({
            'year': 2025, 'month': '6',
            'department_id': self.department.id,
            'company_id': self.company.id,
        })
        sheet.action_generate_lines()
        return {line.employee_id: line for line in sheet.line_ids}

    def test_norm_and_worked_days(self):
        d = self.date
        full = self._employee('Повний місяць', d(2024, 1, 1))
        hired = self._employee('Прийнятий 16.06', d(2025, 6, 16))
        left = self._employee('Звільнений 10.06', d(2024, 1, 1), d(2025, 6, 10),
                              active=False)
        on_leave = self._employee('Відпустка 9–13.06', d(2024, 1, 1))
        sick = self._employee('Лікарняний 23–27.06', d(2024, 1, 1))
        leave = self.env['hr.leave'].create({
            'name': 'Відпустка',
            'employee_id': on_leave.id,
            'work_entry_type_id': self.leave_type.id,
            'request_date_from': d(2025, 6, 9),
            'request_date_to': d(2025, 6, 13),
        })
        if leave.state != 'validate':
            leave.sudo().write({'state': 'validate'})
        self.env['hr.sick.leave'].create({
            'employee_id': sick.id,
            'date_from': d(2025, 6, 23),
            'date_to': d(2025, 6, 27),
            'sick_leave_type': 'illness',
        }).write({'state': 'confirmed'})

        lines = self._generate()
        for employee, worked in ((full, 21), (hired, 11), (left, 7),
                                 (on_leave, 16), (sick, 16)):
            self.assertIn(employee, lines, employee.name)
            self.assertEqual(lines[employee].scheduled_days, 21, employee.name)
            self.assertEqual(lines[employee].worked_days, worked, employee.name)
        self.assertEqual(lines[on_leave].vacation_days, 5)
        self.assertEqual(lines[sick].sick_days, 5)

    def test_employees_without_contract_in_month_skipped(self):
        d = self.date
        never = self._employee('Без договору')
        ended = self._employee('Звільнений у травні', d(2024, 1, 1), d(2025, 5, 31))
        future = self._employee('Прийнятий у липні', d(2025, 7, 1))
        lines = self._generate()
        self.assertNotIn(never, lines)
        self.assertNotIn(ended, lines)
        self.assertNotIn(future, lines)
