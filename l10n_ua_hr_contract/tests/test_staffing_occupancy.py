"""Occupancy is counted on the date of the line, not on today.

Since #300 a position keeps a history of approved lines, each in force from
its own date until the next one starts. `filled_units` counted whoever holds
the post today, so the 2020 line reported the occupancy of the current day.

Covered here:
- a closed period is measured on its last day, one in force on today;
- a version that moved to another post inside the period drops out of it;
- `work_rate` comes from the version in force then, not from the current one;
- a combination is dated too;
- an officer without hr.group_hr_manager reads the field with no AccessError
  — the count rests on `contract_date_*`, which that group guards, so it has
  to go through the stored field's `compute_sudo` rather than run under the
  rights of whoever is writing.

On the fixtures: creating an hr.employee already creates a version dated
today, carrying `self.job`. The positions here are therefore built on `job_2`
— otherwise that version would be counted in today's snapshot and hide the
very thing under test.
"""

from datetime import date

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestStaffingOccupancy(ContractTestCase):

    def setUp(self):
        super().setUp()
        self.today = fields.Date.today()

    def _line(self, date_from, units=1.0, **kwargs):
        vals = {
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job_2.id,
            'units': units,
            'salary': 15000.0,
            'date_from': date_from,
            'state': 'approved',
        }
        vals.update(kwargs)
        return self.env['hr.staffing.table'].create(vals)

    def _holder(self, date_version, **kwargs):
        """An employee whose only version holds job_2 from `date_version`.

        Creating an hr.employee already yields a version dated today; that is
        the one rewritten here, rather than adding a second. Otherwise today's
        snapshot would fall on that automatic version, carrying `self.job`,
        and a check on a historical line would prove nothing.
        """
        employee = self._create_employee()
        vals = {
            'date_version': date_version,
            'contract_date_start': date_version,
            'department_id': self.department.id,
            'job_id': self.job_2.id,
        }
        vals.update(kwargs)
        employee.version_ids.write(vals)
        return employee

    def test_closed_period_is_measured_on_its_own_last_day(self):
        """A line superseded by the next is measured on its own last day."""
        line_old = self._line(date(2020, 1, 1))
        line_new = self._line(date(2023, 1, 1))
        self.assertEqual(line_old.date_end, date(2022, 12, 31))
        self.assertFalse(line_new.date_end)

        self._holder(date(2019, 6, 1),
                     contract_date_end=date(2022, 12, 31), work_rate=1.0)

        # Present on the last day of the old period, and no longer in the
        # one in force.
        self.assertAlmostEqual(line_old.filled_units, 1.0)
        self.assertAlmostEqual(line_old.vacant_units, 0.0)
        self.assertAlmostEqual(line_new.filled_units, 0.0)
        self.assertAlmostEqual(line_new.vacant_units, 1.0)

    def test_move_to_another_position_inside_the_period(self):
        """The version counted is the one in force on the date, not any of
        those that ever carried the position."""
        line_old = self._line(date(2020, 1, 1))
        self._line(date(2024, 1, 1))
        self.assertEqual(line_old.date_end, date(2023, 12, 31))

        employee = self._holder(date(2019, 6, 1), work_rate=1.0)
        # Moved to another post in June 2023: by the end of the line's
        # period the position is no longer held.
        self._create_version(
            employee=employee,
            date_version=date(2023, 6, 1),
            contract_date_start=date(2019, 6, 1),
            contract_date_end=False,
            department_id=self.department.id,
            job_id=self.job.id,
            work_rate=1.0,
        )
        self.assertAlmostEqual(line_old.filled_units, 0.0)

    def test_work_rate_comes_from_the_version_of_that_time(self):
        line_old = self._line(date(2020, 1, 1))
        self._line(date(2024, 1, 1))

        self._holder(date(2019, 6, 1), work_rate=0.5)

        self.assertAlmostEqual(line_old.filled_units, 0.5)
        self.assertAlmostEqual(line_old.vacant_units, 0.5)

    def test_new_line_recounts_the_one_it_supersedes(self):
        """Approving the next line closes the period of the previous one, and
        with it the date that one is measured on."""
        line = self._line(date(2020, 1, 1))
        self._holder(date(2019, 6, 1),
                     contract_date_end=date(2022, 12, 31), work_rate=1.0)
        # While the line is in force it is measured on today, and the person
        # has already left.
        self.assertAlmostEqual(line.filled_units, 0.0)

        self._line(date(2023, 1, 1))
        # Its period now ends on 2022-12-31, and the person is in it.
        self.assertAlmostEqual(line.filled_units, 1.0)

    def test_combining_is_dated_too(self):
        line_old = self._line(date(2020, 1, 1))
        line_new = self._line(date(2025, 1, 1))

        employee = self._create_employee()
        version = self._create_version(
            employee=employee, date_version=date(2024, 1, 1),
            contract_date_start=date(2024, 1, 1))
        combining = self.env['hr.job.combining'].create({
            'employee_id': employee.id,
            'version_id': version.id,
            'combined_job_id': self.job_2.id,
            'combined_department_id': self.department.id,
            'combined_rate': 0.5,
            'date_from': date(2025, 3, 1),
            'surcharge_type': 'percent',
            'surcharge_percent': 50,
            'order_number': 'НК-S01',
            'order_date': date(2025, 2, 25),
        })
        combining.action_activate()

        # Runs from 2025-03-01: the line in force sees it, the one closed on
        # 2024-12-31 does not.
        self.assertAlmostEqual(line_new.filled_units, 0.5)
        self.assertAlmostEqual(line_old.filled_units, 0.0)

    def test_officer_without_manager_group_reads_the_field(self):
        """The count reads contract_date_*, guarded by hr.group_hr_manager.

        The officer has to both read the field and write a version that drags
        the recount along: were that recount to run under their own rights, it
        would raise an AccessError.
        """
        officer = self.env['res.users'].create({
            'name': 'HR Officer',
            'login': 'ua_hr_officer_occupancy',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('hr.group_hr_user').id,
            ])],
        })
        self.assertFalse(officer.has_group('hr.group_hr_manager'))

        line = self._line(date(2020, 1, 1))
        version = self._holder(date(2019, 6, 1), work_rate=1.0).version_ids
        self.assertAlmostEqual(line.filled_units, 1.0)

        with self.assertRaises(AccessError):
            version.with_user(officer).read(['contract_date_start'])

        # A version written by the officer drags the recount along.
        version.with_user(officer).write({'job_id': self.job.id})
        self.env.flush_all()
        self.assertAlmostEqual(
            line.with_user(officer).filled_units, 0.0)
