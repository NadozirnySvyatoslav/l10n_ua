"""Every company has its own set of UA working schedules.

Regression test for the company mix-up: before 19.0.6.0.0 the ten schedules
from the data file were a single record per database, belonged to one company,
and changing company_id on such a schedule switched it for all the other
companies at once.
"""

from odoo.tests import tagged

from .common import ContractTestCase

UA_CALENDAR_CODES = [
    'STD40', 'STD36', 'STD24', 'PART20', 'STD6D',
    'FLEX', 'SHIFT2X2', 'SHIFT1X3', 'SHIFT3X3', 'SUMM',
]


@tagged('post_install', '-at_install')
class TestResourceCalendarMultiCompany(ContractTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Друга компанія'})

    def _calendars_of(self, company):
        return self.env['resource.calendar'].search([
            ('company_id', '=', company.id), ('ua_code', '!=', False)])

    def test_templates_are_not_selectable(self):
        """The data file templates carry no company and stay archived."""
        for code in UA_CALENDAR_CODES:
            template = self.env.ref(
                'l10n_ua_hr_contract.resource_calendar_ua_%s' % code.lower())
            self.assertFalse(
                template.company_id,
                'Template %s is bound to a company' % code)
            self.assertFalse(
                template.active, 'Template %s is not archived' % code)

    def test_new_company_gets_its_own_set(self):
        """res.company.create() gives the company its own copy of every schedule."""
        codes = set(self._calendars_of(self.company_b).mapped('ua_code'))
        self.assertEqual(codes, set(UA_CALENDAR_CODES))

    def test_copies_are_distinct_records(self):
        """Copies of different companies are separate records, not a shared one."""
        own = self._calendars_of(self.env.company).filtered(
            lambda c: c.ua_code == 'STD40')
        other = self._calendars_of(self.company_b).filtered(
            lambda c: c.ua_code == 'STD40')
        self.assertTrue(own and other)
        self.assertNotEqual(own.id, other.id)

    def test_editing_hours_does_not_leak(self):
        """Editing hours in one company leaves the other alone - the actual bug."""
        own = self._calendars_of(self.env.company).filtered(
            lambda c: c.ua_code == 'STD40')
        other = self._calendars_of(self.company_b).filtered(
            lambda c: c.ua_code == 'STD40')
        before = other.hours_per_week
        own.attendance_ids[0].hour_to = 12.0
        self.assertEqual(other.hours_per_week, before)

    def test_norms_survive_the_copy(self):
        """The copy keeps the template norm, flexible schedules included.

        hours_per_week is declared copy=False and its compute skips flexible
        schedules, so without an explicit carry-over the shift cycles would
        end up at zero.
        """
        for calendar in self._calendars_of(self.company_b):
            template = self.env.ref(
                'l10n_ua_hr_contract.resource_calendar_ua_%s'
                % calendar.ua_code.lower())
            self.assertAlmostEqual(
                calendar.hours_per_week, template.hours_per_week, places=1,
                msg='Weekly norm lost in the copy of %s' % calendar.ua_code)
            self.assertGreater(
                calendar.hours_per_week, 0.0,
                'Zero weekly norm in the copy of %s' % calendar.ua_code)

    def test_copy_keeps_the_template_name(self):
        """The core copy_data appends " (copy)" - the name must stay clean."""
        for calendar in self._calendars_of(self.company_b):
            self.assertNotIn('(copy)', calendar.name)

    def test_materialisation_is_idempotent(self):
        """A second run (module update) creates no duplicates."""
        before = len(self._calendars_of(self.company_b))
        self.company_b._l10n_ua_create_resource_calendars()
        self.assertEqual(len(self._calendars_of(self.company_b)), before)

    def test_archived_copy_is_not_duplicated(self):
        """A schedule the company archived must not come back as a duplicate.

        resource_calendar_ids hides archived records, so the existence check
        has to run with active_test=False.
        """
        calendar = self._calendars_of(self.company_b).filtered(
            lambda c: c.ua_code == 'SHIFT2X2')
        calendar.active = False
        self.company_b._l10n_ua_create_resource_calendars()
        again = self.env['resource.calendar'].with_context(
            active_test=False).search([
                ('company_id', '=', self.company_b.id),
                ('ua_code', '=', 'SHIFT2X2')])
        self.assertEqual(len(again), 1)

    def _hr_user(self, company):
        """An HR officer allowed in a single company."""
        return self.env['res.users'].create({
            'name': 'HR officer of %s' % company.name,
            'login': 'hr_officer_%s' % company.id,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'group_ids': [(4, self.env.ref('hr.group_hr_user').id)],
        })

    def test_hr_officer_sees_only_own_company_schedules(self):
        """The record rule hides the schedules of the other companies.

        The core ships a multi-company rule for resource.resource and
        resource.calendar.leaves but not for resource.calendar
        (addons/resource/security/resource_security.xml), so this one comes
        from the module.
        """
        user = self._hr_user(self.company_b)
        visible = self.env['resource.calendar'].with_user(user).search([])
        companies = visible.mapped('company_id')
        self.assertEqual(
            companies, self.company_b,
            'An HR officer of one company sees schedules of: %s'
            % ', '.join(companies.mapped('name')))

    def test_hr_officer_still_reads_the_own_schedule(self):
        """The rule must not lock the officer out of their own schedules."""
        user = self._hr_user(self.company_b)
        own = self._calendars_of(self.company_b)
        self.assertEqual(
            len(own.with_user(user).mapped('hours_per_week')), len(own))

    def test_hr_officer_sees_no_foreign_allowances(self):
        """hr.version.allowance is scoped through its version, not its own
        company_id - record rules do not cascade through a many2one, so the
        rule has to walk version_id.company_id explicitly.
        """
        # Create the employee instead of fishing one out of the database:
        # a fresh install carries no employees at all.
        employee = self.env['hr.employee'].create({
            'name': 'Гнатюк Олег Петрович',
            'company_id': self.env.company.id,
        })
        version = employee.version_id
        self.assertTrue(version, 'no version to attach an allowance to')
        allowance = self.env['hr.version.allowance'].create({
            'version_id': version.id,
            'allowance_type_id': self.allowance_seniority.id,
            'percent': 10.0,
        })
        user = self._hr_user(self.company_b)
        seen = self.env['hr.version.allowance'].with_user(user).search([])
        self.assertNotIn(allowance, seen)

    def test_employee_of_each_company_takes_its_own_calendar(self):
        """Employee working for both companies: own schedule in each of them."""
        own = self._calendars_of(self.env.company).filtered(
            lambda c: c.ua_code == 'STD40')
        other = self._calendars_of(self.company_b).filtered(
            lambda c: c.ua_code == 'STD40')

        employee_a = self.env['hr.employee'].create({
            'name': 'Іщенко Катерина Андріївна',
            'company_id': self.env.company.id,
            'resource_calendar_id': own.id,
        })
        employee_b = self.env['hr.employee'].create({
            'name': 'Іщенко Катерина Андріївна',
            'company_id': self.company_b.id,
            'resource_calendar_id': other.id,
        })

        self.assertEqual(employee_a.resource_calendar_id.company_id,
                         self.env.company)
        self.assertEqual(employee_b.resource_calendar_id.company_id,
                         self.company_b)

    def test_copy_carries_the_time_off_of_the_template(self):
        """A company's copy brings the schedule's time off along.

        This is what lets the 19.0.6.0.0 migration leave
        resource_calendar_leaves alone: the rows belong to the calendar (their
        company_id is a stored compute over calendar_id.company_id), and every
        company already gets its own. Repointing them as well put the original
        on the same copy as its duplicate, leaving one company with the public
        holiday twice - which core's own overlap constraint forbids.
        """
        template = self.env.ref('l10n_ua_hr_contract.resource_calendar_ua_std40')
        self.env['resource.calendar.leaves'].create({
            'name': 'ТЕСТ Корпоративний вихідний',
            'calendar_id': template.id,
            'date_from': '2099-10-13 00:00:00',
            'date_to': '2099-10-13 23:59:59',
        })

        company = self.env['res.company'].create({'name': 'ТЕСТ Третя компанія'})

        copy = self._calendars_of(company).filtered(lambda c: c.ua_code == 'STD40')
        carried = copy.leave_ids.filtered(
            lambda l: l.name == 'ТЕСТ Корпоративний вихідний')
        self.assertEqual(len(carried), 1,
                         'the copy carries the time off exactly once')
        self.assertEqual(carried.company_id, company,
                         'the copied time off belongs to the company')
