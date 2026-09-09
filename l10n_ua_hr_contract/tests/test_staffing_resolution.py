"""Tests for deriving the staffing table line from the position.

`staffing_line_id` is no longer picked by hand: it follows department + job on
the date the version is in force. Covered here:
- resolution by date (current, superseded and future-dated versions)
- a permanent contract whose salary is revised yearly without new versions
- unapproved lines and uncovered positions raise nothing
- the salary range warns instead of blocking
- the wage suggestion fires from a change of position
- the panel on the card follows the position inside the form, before saving
- resolution is batched: one lookup for a whole recordset

Note on the fixtures: creating an hr.employee already creates a version dated
today, and that version is the current one. Tests about the present therefore
work on `employee.current_version_id`; a test about the past adds versions
dated earlier, which makes the added ones superseded — exactly as they would be
in a real record.
"""

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import Form, tagged

from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestStaffingResolution(ContractTestCase):

    def setUp(self):
        super().setUp()
        self.today = fields.Date.today()

    def _line(self, **kwargs):
        """An approved line covering everything up to today by default.

        `date_from` deliberately reaches well into the past: the shared
        `_create_version()` helper dates its versions in 2025, and a line
        starting today would not cover them.
        """
        vals = {
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'salary': 25000.0,
            'date_from': self.today - relativedelta(years=5),
            'state': 'approved',
        }
        vals.update(kwargs)
        return self.env['hr.staffing.table'].create(vals)

    def _version(self, employee, date_version, **kwargs):
        """Extra version for an employee, carrying an explicit position.

        The shared `_create_version()` passes neither department nor job, so a
        version built with it has no position at all and resolves to nothing -
        correctly so, but that is not what these tests are about.
        """
        vals = {
            'department_id': self.department.id,
            'job_id': self.job.id,
        }
        vals.update(kwargs)
        return self._create_version(
            employee=employee, date_version=date_version, **vals)

    def _employee(self, job=None, department=None):
        """Employee whose current version is dated today."""
        ContractTestCase._version_counter += 1
        return self.env['hr.employee'].create({
            'name': 'Staffing Test %s' % ContractTestCase._version_counter,
            'company_id': self.company.id,
            'department_id': (department or self.department).id,
            'job_id': (job or self.job).id,
        })

    # === Resolution ===

    def test_current_version_resolves_to_approved_line(self):
        line = self._line()
        employee = self._employee()
        self.assertEqual(employee.current_version_id.staffing_line_id, line)

    def test_draft_line_is_not_resolved(self):
        self._line(state='draft')
        employee = self._employee()
        self.assertFalse(employee.current_version_id.staffing_line_id)

    def test_archived_line_is_not_resolved(self):
        self._line(state='archived')
        employee = self._employee()
        self.assertFalse(employee.current_version_id.staffing_line_id)

    def test_position_outside_staffing_table_is_not_an_error(self):
        """Keeping a staffing table is optional - an empty result is normal."""
        self._line()
        employee = self._employee(job=self.job_2)
        self.assertFalse(employee.current_version_id.staffing_line_id)

    def test_line_of_another_department_is_not_resolved(self):
        other = self.env['hr.department'].create({
            'name': 'Other Department', 'company_id': self.company.id,
        })
        self._line(department_id=other.id)
        employee = self._employee()
        self.assertFalse(employee.current_version_id.staffing_line_id)

    def test_superseded_version_resolves_to_its_own_period(self):
        """A superseded version is read against the table of its own period.

        Three versions: two added in the past plus the one created with the
        employee. The earliest is capped by the middle one, so it must see the
        line that was in force back then, not the current one.
        """
        old_line = self._line(
            date_from=date(2024, 1, 1), date_to=date(2025, 5, 31),
            salary=18000.0)
        new_line = self._line(date_from=date(2025, 6, 1), salary=30000.0)

        employee = self._employee()
        first = self._version(employee, date(2024, 6, 1))
        self._version(employee, date(2025, 6, 1))

        self.assertEqual(first.staffing_line_id, old_line)
        self.assertEqual(
            employee.current_version_id.staffing_line_id, new_line)

    def test_permanent_contract_follows_the_current_line(self):
        """The ordinary Ukrainian case: one open-ended version whose salary is
        revised every year without anyone creating a new version. The card must
        show the table in force now, not the one that applied at hiring."""
        self._line(
            date_from=self.today - relativedelta(years=2),
            date_to=self.today - relativedelta(years=1, days=1),
            salary=18000.0)
        current_line = self._line(
            date_from=self.today - relativedelta(years=1), salary=30000.0)

        employee = self._employee()

        self.assertEqual(
            employee.current_version_id.staffing_line_id, current_line)

    def test_future_version_resolves_to_its_start_date(self):
        """A planned transfer reads the table in force on its start date."""
        in_a_year = self.today + relativedelta(years=1)
        self._line(date_to=in_a_year - relativedelta(days=1), salary=25000.0)
        future_line = self._line(date_from=in_a_year, salary=40000.0)

        employee = self._employee()
        future = self._version(employee, in_a_year)

        self.assertEqual(future.staffing_line_id, future_line)

    def test_panel_follows_the_position_inside_the_form(self):
        """The panel must react to the position before the record is saved.

        The card resolves the line itself instead of reading it from
        `current_version_id`: that field is a stored compute over
        `version_ids.date_version`, so a related field routed through it stays
        empty until save — the panel showed nothing while the HR officer was
        still choosing the position.
        """
        line = self._line()
        employee = self._employee(job=self.job_2)
        self.assertFalse(employee.staffing_line_id)

        with Form(employee) as form:
            form.job_id = self.job

            self.assertEqual(form.staffing_line_id, line)
            self.assertEqual(form.staffing_salary, line.salary)

    def test_card_and_version_agree(self):
        """Both read the same rule, so they cannot answer differently."""
        line = self._line()
        employee = self._employee()

        self.assertEqual(employee.staffing_line_id, line)
        self.assertEqual(
            employee.current_version_id.staffing_line_id, line)

    # === Salary range ===

    def test_wage_outside_range_warns_without_blocking(self):
        self._line(salary=20000.0, salary_min=16000.0, salary_max=22000.0)
        employee = self._employee()
        version = employee.current_version_id
        version.write({'wage': 20000})
        before = len(employee.message_ids)

        # Must not raise - that is the whole point of replacing the constraint
        # with a warning.
        version.write({'wage': 35000})

        self.assertEqual(version.wage, 35000)
        self.assertEqual(len(employee.message_ids), before + 1)
        self.assertIn('staffing table', employee.message_ids[0].body)

    def test_wage_inside_range_is_silent(self):
        self._line(salary=20000.0, salary_min=16000.0, salary_max=22000.0)
        employee = self._employee()
        version = employee.current_version_id
        version.write({'wage': 18000})
        before = len(employee.message_ids)

        version.write({'wage': 21000})

        self.assertEqual(len(employee.message_ids), before)

    def test_unchanged_wage_does_not_repeat_the_warning(self):
        """Saving the same form twice must not post the same warning twice."""
        self._line(salary=20000.0, salary_max=22000.0)
        employee = self._employee()
        version = employee.current_version_id
        version.write({'wage': 35000})
        before = len(employee.message_ids)

        version.write({'wage': 35000})

        self.assertEqual(len(employee.message_ids), before)

    def test_line_without_range_is_silent(self):
        self._line(salary=20000.0)
        employee = self._employee()
        version = employee.current_version_id
        version.write({'wage': 99000})
        before = len(employee.message_ids)

        version.write({'wage': 120000})

        self.assertEqual(len(employee.message_ids), before)

    def test_position_without_line_is_silent(self):
        """No staffing line means no range to compare against."""
        employee = self._employee(job=self.job_2)
        version = employee.current_version_id
        before = len(employee.message_ids)

        version.write({'wage': 120000})

        self.assertEqual(len(employee.message_ids), before)

    # === Wage suggestion ===

    def test_wage_suggested_from_position(self):
        """The suggestion now fires from the position, not the staffing line."""
        self._line(salary=30000.0)
        employee = self._employee()
        version = self.env['hr.version'].new({
            'employee_id': employee.id,
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'date_version': self.today,
            'wage': 0.0,
        })

        version._onchange_job_suggest_wage()

        self.assertEqual(version.wage, 30000.0)

    def test_existing_wage_is_not_overwritten_by_suggestion(self):
        self._line(salary=30000.0)
        employee = self._employee()
        version = self.env['hr.version'].new({
            'employee_id': employee.id,
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'date_version': self.today,
            'wage': 27000.0,
        })

        version._onchange_job_suggest_wage()

        self.assertEqual(version.wage, 27000.0)

    # === Batching ===

    def test_resolution_is_batched(self):
        """Reading a recordset must cost one lookup, not one per record.

        The field is not stored, so it is computed on every read - a query per
        record would be felt immediately on a list of versions.
        """
        self._line()
        versions = self.env['hr.version'].browse(
            [self._employee().current_version_id.id for _ in range(3)])

        calls = []
        Staffing = type(self.env['hr.staffing.table'])
        original = Staffing._resolve_batch

        def counting(model, keys):
            calls.append(len(keys))
            return original(model, keys)

        self.patch(Staffing, '_resolve_batch', counting)
        versions.invalidate_recordset(['staffing_line_id'])
        versions.mapped('staffing_line_id')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], 3)


@tagged('post_install', '-at_install')
class TestStaffingResolveHelper(ContractTestCase):
    """Direct tests of the resolver - the entry point for the rest of the code."""

    def test_resolve_requires_all_parts(self):
        Staffing = self.env['hr.staffing.table']
        self.assertFalse(Staffing._resolve(
            self.company, self.department, self.job, False))
        self.assertFalse(Staffing._resolve(
            self.company, self.env['hr.department'], self.job,
            fields.Date.today()))

    def test_resolve_picks_the_line_in_force(self):
        Staffing = self.env['hr.staffing.table']
        closed = Staffing.create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'salary': 18000.0,
            'date_from': date(2024, 1, 1),
            'date_to': date(2024, 12, 31),
            'state': 'approved',
        })
        current = Staffing.create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'salary': 30000.0,
            'date_from': date(2025, 1, 1),
            'state': 'approved',
        })

        self.assertEqual(
            Staffing._resolve(self.company, self.department, self.job,
                              date(2024, 6, 1)), closed)
        self.assertEqual(
            Staffing._resolve(self.company, self.department, self.job,
                              date(2025, 6, 1)), current)
        self.assertFalse(
            Staffing._resolve(self.company, self.department, self.job,
                              date(2023, 6, 1)))
