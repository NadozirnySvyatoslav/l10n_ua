# Part of Odoo. See LICENSE file for full copyright and licensing details.

from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger
from odoo.exceptions import UserError, ValidationError
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG
from datetime import date
from dateutil.relativedelta import relativedelta

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestHrStaffingTable(TestHrUaBase):
    """Test hr.staffing.table model."""

    def _create_staffing_record(self, **kwargs):
        """Helper to create staffing table record."""
        vals = {
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'units': 1.0,
            'salary': 15000.0,
            'date_from': date.today(),
        }
        vals.update(kwargs)
        return self.env['hr.staffing.table'].create(vals)

    def test_staffing_table_creation(self):
        """Test basic staffing table record creation."""
        record = self._create_staffing_record()

        self.assertEqual(record.units, 1.0)
        self.assertEqual(record.salary, 15000.0)
        self.assertEqual(record.state, 'draft')

    def test_staffing_table_name_computation(self):
        """Test name computed field."""
        record = self._create_staffing_record()

        expected_name = f"{self.department.name} / {self.job.name}"
        self.assertEqual(record.name, expected_name)

    def test_total_salary_fund_computation(self):
        """Test total_salary_fund computed field."""
        record = self._create_staffing_record(
            units=2.5,
            salary=10000.0,
        )

        self.assertEqual(record.total_salary_fund, 25000.0)

    def test_units_validation_zero(self):
        """Test that zero units is rejected."""
        with self.assertRaises(ValidationError):
            self._create_staffing_record(units=0)

    def test_units_validation_negative(self):
        """Test that negative units is rejected."""
        with self.assertRaises(ValidationError):
            self._create_staffing_record(units=-1)

    def test_units_fractional(self):
        """Test fractional units (part-time positions)."""
        record = self._create_staffing_record(units=0.5)
        self.assertEqual(record.units, 0.5)
        self.assertEqual(record.total_salary_fund, 7500.0)

    def test_date_validation(self):
        """Test date range validation."""
        with self.assertRaises(ValidationError):
            self._create_staffing_record(
                date_from=date(2024, 12, 31),
                date_to=date(2024, 1, 1),  # Before date_from
            )

    def test_date_validation_same_date(self):
        """Test that same date_from and date_to is allowed."""
        record = self._create_staffing_record(
            date_from=date(2024, 6, 15),
            date_to=date(2024, 6, 15),
        )
        self.assertEqual(record.date_from, record.date_to)

    def test_a_new_line_supersedes_the_previous_one(self):
        """A raise is entered as a new line; the previous one ends by itself.

        Nothing is written to the earlier line: its period ends the day before
        the next one starts, and that is derived, not stored. `date_to` stays
        empty because the position was not discontinued — it was superseded.
        """
        old = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)

        new = self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0)

        old.invalidate_recordset()
        self.assertEqual(old.date_end, date(2024, 12, 31))
        self.assertFalse(old.date_to)
        self.assertEqual(old.state, 'approved')
        self.assertFalse(new.date_end)
        self.assertTrue(new.is_current)
        self.assertFalse(old.is_current)

    def test_history_resolves_by_period(self):
        """Each period answers for its own dates."""
        Staffing = self.env['hr.staffing.table']
        self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0)

        for day, expected in ((date(2024, 6, 1), 15000.0),
                              (date(2025, 6, 1), 20000.0)):
            line = Staffing._resolve(
                self.company, self.department, self.job, day)
            self.assertEqual(line.salary, expected)

    def test_unapproving_gives_the_previous_line_back(self):
        """Undoing an approval must leave the position covered.

        Nothing was written to the earlier line when it was superseded, so
        there is nothing to undo: it is in force again the moment the later
        line stops being approved.
        """
        old = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        new = self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0)

        new.action_draft()

        old.invalidate_recordset()
        self.assertFalse(old.date_end)
        self.assertTrue(old.is_current)
        line = self.env['hr.staffing.table']._resolve(
            self.company, self.department, self.job, date(2025, 6, 1))
        self.assertEqual(line, old)

    def test_a_sequence_can_be_approved_at_once(self):
        """Approving several periods of one position together is legitimate."""
        first = self._create_staffing_record(
            state='draft', date_from=date(2025, 1, 1), salary=18000.0)
        second = self._create_staffing_record(
            state='draft', date_from=date(2026, 1, 1), salary=21000.0)

        (first | second).action_approve()

        first.invalidate_recordset()
        self.assertEqual(first.date_end, date(2025, 12, 31))
        self.assertFalse(second.date_end)

    def test_discontinued_position_stops_resolving(self):
        """`date_to` ends the position: after it, nothing applies."""
        Staffing = self.env['hr.staffing.table']
        self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0,
            date_to=date(2025, 6, 30))

        self.assertEqual(
            Staffing._resolve(self.company, self.department, self.job,
                              date(2025, 3, 1)).salary, 20000.0)
        # Past the closing date the position is gone — the line it superseded
        # does not come back to life.
        self.assertFalse(
            Staffing._resolve(self.company, self.department, self.job,
                              date(2025, 9, 1)))

    def test_same_start_date_is_refused_by_the_database(self):
        """Two approved lines starting the same day would make the resolution
        depend on the query plan."""
        self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1))

        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._create_staffing_record(
                state='approved', date_from=date(2025, 1, 1))
            self.env.flush_all()

    def test_an_approved_line_cannot_be_archived(self):
        """Archiving the line in force would silently restore the previous
        salary: the resolution only looks at approved lines."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))

        with self.assertRaises(UserError):
            line.action_archive()

    def test_a_mistaken_approval_is_undone_with_set_to_draft(self):
        """The officer's way back: draft it, then discard it if unwanted."""
        old = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        wrong = self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=99000.0)

        wrong.action_draft()
        wrong.action_archive()

        self.assertEqual(wrong.state, 'archived')
        line = self.env['hr.staffing.table']._resolve(
            self.company, self.department, self.job, date(2025, 6, 1))
        self.assertEqual(line, old)

    def test_an_approved_line_cannot_be_deleted(self):
        """Deleting history is worse than archiving it: the chatter that would
        have explained the change goes with the record."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))

        with self.assertRaises(UserError):
            line.action_archive()
        with self.assertRaises(UserError):
            line.unlink()

        # Both doors lead through the same undo.
        line.action_draft()
        line.unlink()

    def test_only_the_fields_that_decide_a_salary_are_flagged(self):
        """Staff units never reach a payslip — warning about them would be
        untrue, and untrue warnings stop being read."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))
        backdated = lambda: len(line.message_ids.filtered(
            lambda m: 'applies from' in (m.body or '')
            or 'заднім числом' in (m.body or '')))
        before = backdated()

        line.write({'units': 3.0})
        self.assertEqual(backdated(), before)

        line.write({'salary': 25000.0})
        self.assertEqual(backdated(), before + 1)

    def test_only_the_last_approval_can_be_undone(self):
        """Drafting a superseded line would delete a period from the history —
        the same damage archiving and deleting are refused for, through a
        button whose name promises the opposite."""
        old = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        new = self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0)

        with self.assertRaises(UserError):
            old.action_draft()

        # Undo the later approval, and the earlier one is the last again.
        new.action_draft()
        old.action_draft()
        self.assertEqual(old.state, 'draft')

    def test_uninstalling_the_module_may_remove_approved_lines(self):
        """The demo data ships approved lines with xml_ids; refusing here would
        leave the module impossible to uninstall."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))

        line.with_context(**{MODULE_UNINSTALL_FLAG: True}).unlink()

        self.assertFalse(line.exists())

    def test_the_field_the_filter_and_the_resolution_agree(self):
        """One rule, asked three ways: on a record, through a search, and by
        payroll. A position discontinued long ago is in force nowhere — none of
        the three may offer the line it superseded years earlier."""
        Staffing = self.env['hr.staffing.table']
        lines = (
            self._create_staffing_record(
                state='approved', date_from=date(2024, 1, 1), salary=15000.0)
            | self._create_staffing_record(
                state='approved', date_from=date(2025, 1, 1), salary=20000.0,
                date_to=date(2025, 6, 30))
        )

        self.assertFalse(lines.filtered('is_current'))
        self.assertFalse(Staffing.search([
            ('is_current', '=', True), ('id', 'in', lines.ids)]))
        self.assertFalse(Staffing._resolve(
            self.company, self.department, self.job, date(2026, 1, 1)))

    def test_the_three_agree_on_a_plain_history(self):
        """And they pick the same line when there is one to pick."""
        Staffing = self.env['hr.staffing.table']
        old = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1), salary=15000.0)
        current = self._create_staffing_record(
            state='approved', date_from=date(2025, 1, 1), salary=20000.0)

        self.assertEqual((old | current).filtered('is_current'), current)
        self.assertEqual(Staffing.search([
            ('is_current', '=', True),
            ('id', 'in', (old | current).ids)]), current)
        self.assertEqual(Staffing._resolve(
            self.company, self.department, self.job, date(2026, 1, 1)), current)

    def test_discontinuing_an_occupied_position_is_flagged(self):
        """Closing a position somebody still holds is allowed — an order is an
        order — but past that date payroll reads nothing for them."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))
        self.env['hr.employee'].create({
            'name': 'Occupant',
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
        })
        self.env.flush_all()
        line.invalidate_recordset()
        self.assertTrue(line.filled_units)
        before = len(line.message_ids)

        # A closing date in the future, and relative to today: only the
        # occupancy note can fire, so the count says what it means. A date in
        # the past would also trip the retroactive warning — and a hard-coded
        # one quietly becomes past as time moves on.
        line.write({'date_to': date.today() + relativedelta(years=2)})

        self.assertEqual(len(line.message_ids), before + 1)

    def test_discontinuing_a_vacant_position_is_silent(self):
        """Nobody to warn about."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))
        self.env.flush_all()
        line.invalidate_recordset()
        self.assertFalse(line.filled_units)
        before = len(line.message_ids)

        line.write({'date_to': date.today() + relativedelta(years=2)})

        self.assertEqual(len(line.message_ids), before)

    def test_moving_a_start_forward_is_flagged_too(self):
        """Pushing a start date into the future takes months out of the history
        as surely as back-dating puts them in. Judging by the value left behind
        would miss it: after the write the line no longer looks retroactive."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2024, 1, 1))
        before = len(line.message_ids)

        line.write({'date_from': date(2030, 1, 1)})

        self.assertEqual(len(line.message_ids), before + 1)
        # And the period it used to cover really is gone.
        self.assertFalse(self.env['hr.staffing.table']._resolve(
            self.company, self.department, self.job, date(2025, 6, 1)))

    def test_a_future_line_moved_within_the_future_is_silent(self):
        """Nothing that has been paid is affected."""
        line = self._create_staffing_record(
            state='approved', date_from=date(2030, 1, 1))
        before = len(line.message_ids)

        line.write({'date_from': date(2031, 1, 1)})

        self.assertEqual(len(line.message_ids), before)

    def test_drafts_and_archives_are_not_constrained(self):
        """Drafts are working copies an officer may prepare several of, and an
        archived line is outside the resolution altogether."""
        self._create_staffing_record(state='approved', date_from=date(2025, 1, 1))
        self._create_staffing_record(state='draft', date_from=date(2025, 1, 1))
        self._create_staffing_record(state='draft', date_from=date(2025, 1, 1))
        self._create_staffing_record(state='archived', date_from=date(2025, 1, 1))

        self.env.flush_all()
        lines = self.env['hr.staffing.table'].search([
            ('department_id', '=', self.department.id),
            ('job_id', '=', self.job.id),
        ])
        self.assertEqual(len(lines), 4)

    def test_salary_range_validation(self):
        """Test salary range validation."""
        # Min > Max should fail
        with self.assertRaises(ValidationError):
            self._create_staffing_record(
                salary=15000,
                salary_min=20000,
                salary_max=10000,
            )

    def test_salary_below_minimum(self):
        """Test that salary below minimum is rejected."""
        with self.assertRaises(ValidationError):
            self._create_staffing_record(
                salary=8000,
                salary_min=10000,
                salary_max=20000,
            )

    def test_salary_above_maximum(self):
        """Test that salary above maximum is rejected."""
        with self.assertRaises(ValidationError):
            self._create_staffing_record(
                salary=25000,
                salary_min=10000,
                salary_max=20000,
            )

    def test_salary_within_range(self):
        """Test valid salary within range."""
        record = self._create_staffing_record(
            salary=15000,
            salary_min=10000,
            salary_max=20000,
        )
        self.assertEqual(record.salary, 15000)

    def test_filled_units_computation(self):
        """Test filled_units computed field."""
        record = self._create_staffing_record(units=3.0)

        # Draft state - no filled units
        self.assertEqual(record.filled_units, 0.0)

        # Approve the record
        record.action_approve()

        # No employees yet - force recompute
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 0.0)

        # Create employees in the same department and job
        self._create_employee()
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 1.0)

        self._create_employee(name='Employee 2')
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 2.0)

    def test_vacant_units_computation(self):
        """Test vacant_units computed field."""
        record = self._create_staffing_record(units=3.0)
        record.action_approve()

        # No employees - all vacant
        record._compute_filled_units()
        record._compute_vacant_units()
        self.assertEqual(record.vacant_units, 3.0)

        # Add one employee
        self._create_employee()
        record._compute_filled_units()
        record._compute_vacant_units()
        self.assertEqual(record.vacant_units, 2.0)

    def test_vacant_units_never_negative(self):
        """Test that vacant_units is never negative (overstaffed)."""
        record = self._create_staffing_record(units=1.0)
        record.action_approve()

        # Create more employees than positions
        self._create_employee(name='Employee 1')
        self._create_employee(name='Employee 2')
        self._create_employee(name='Employee 3')
        record._compute_filled_units()
        record._compute_vacant_units()

        # Vacant should be 0, not negative
        self.assertEqual(record.vacant_units, 0.0)
        self.assertEqual(record.filled_units, 3.0)

    def test_state_transitions(self):
        """Test state transitions.

        Approved no longer goes straight to archived: an approved line is the
        record payslips are calculated from, and taking it out of the
        resolution would hand the position back to the salary of the period
        before it. The way back is through draft.
        """
        record = self._create_staffing_record()

        # Initial state
        self.assertEqual(record.state, 'draft')

        # Draft -> Approved
        record.action_approve()
        self.assertEqual(record.state, 'approved')

        # Approved -> Draft: undoing an approval made by mistake.
        record.action_draft()
        self.assertEqual(record.state, 'draft')

        # Draft -> Archived: a working copy may be discarded.
        record.action_archive()
        self.assertEqual(record.state, 'archived')

        # Archived -> Draft
        record.action_draft()
        self.assertEqual(record.state, 'draft')

    def test_order_fields(self):
        """Test order number and date fields."""
        record = self._create_staffing_record(
            order_number='ШР-001/2024',
            order_date=date(2024, 1, 15),
        )

        self.assertEqual(record.order_number, 'ШР-001/2024')
        self.assertEqual(record.order_date, date(2024, 1, 15))


@tagged('post_install', '-at_install')
class TestHrStaffingTableIntegration(TestHrUaBase):
    """Integration tests for staffing table with employees."""

    def test_employee_department_change(self):
        """Test that filled_units updates when employee changes department."""
        # Create second department
        dept2 = self.env['hr.department'].create({
            'name': 'Department 2',
            'company_id': self.company.id,
        })

        record = self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'units': 2.0,
            'salary': 15000.0,
            'date_from': date.today(),
            'state': 'approved',
        })

        employee = self._create_employee()
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 1.0)

        # Move employee to another department
        employee.department_id = dept2
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 0.0)

    def test_employee_job_change(self):
        """Test that filled_units updates when employee changes job."""
        # Create second job
        job2 = self.env['hr.job'].create({
            'name': 'Job 2',
            'company_id': self.company.id,
            'department_id': self.department.id,
        })

        record = self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'units': 2.0,
            'salary': 15000.0,
            'date_from': date.today(),
            'state': 'approved',
        })

        employee = self._create_employee()
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 1.0)

        # Change employee job
        employee.job_id = job2
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 0.0)

    def test_employee_archived(self):
        """Test that archived employees don't count in filled_units."""
        record = self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'units': 2.0,
            'salary': 15000.0,
            'date_from': date.today(),
            'state': 'approved',
        })

        employee = self._create_employee()
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 1.0)

        # Archive employee
        employee.active = False
        record._compute_filled_units()
        self.assertEqual(record.filled_units, 0.0)


@tagged('post_install', '-at_install')
class TestStaffingTableMultiCompany(TestHrUaBase):
    """Multi-company isolation для hr.staffing.table."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({
            'name': 'Company B',
        })
        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Dept B',
            'company_id': cls.company_b.id,
        })
        cls.job_b = cls.env['hr.job'].create({
            'name': 'Job B',
            'company_id': cls.company_b.id,
            'department_id': cls.dept_b.id,
        })

    def test_onchange_company_resets_cross_company_dept(self):
        """Зміна company_id скидає department_id якщо він з іншої компанії."""
        record = self.env['hr.staffing.table'].new({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
        })
        record.company_id = self.company_b
        record._onchange_company_id()
        self.assertFalse(record.department_id,
            'Department from other company must be cleared')
        self.assertFalse(record.job_id,
            'Job from other company must be cleared')

    def test_onchange_company_keeps_shared_records(self):
        """Shared records (company_id=False) не скидаються."""
        shared_dept = self.env['hr.department'].create({
            'name': 'Shared Dept',
            'company_id': False,
        })
        record = self.env['hr.staffing.table'].new({
            'company_id': self.company.id,
            'department_id': shared_dept.id,
        })
        record.company_id = self.company_b
        record._onchange_company_id()
        self.assertEqual(record.department_id, shared_dept,
            'Shared department must remain after company switch')
