"""Unused vacation as of a date: the figure the dismissal order compensates
and the remaining vacation certificate lists.

Public holidays are removed in every test except the one about them: under
martial law they are working days, and the calendar is kept empty.
"""

import importlib.util
import os
import re
from datetime import date, datetime

from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_hr_documents.tools import compensable_vacation_days as days


@tagged('post_install', '-at_install')
class TestVacationEntitlement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['resource.calendar.leaves'].search([('resource_id', '=', False)]).unlink()
        cls.Entitlement = cls.env['hr.vacation.entitlement']
        cls.basic = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.hazard = cls.env.ref('l10n_ua_hr_holidays.leave_type_additional_hazard')
        cls.additional = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_additional')
        cls.children = cls.env.ref('l10n_ua_hr_holidays.leave_type_social_children')
        cls.sick = cls.env.ref('l10n_ua_hr_holidays.leave_type_sick')
        cls.unpaid = cls.env.ref('l10n_ua_hr_holidays.leave_type_unpaid')
        cls.unpaid_abroad = cls.env.ref('l10n_ua_hr_holidays.leave_type_unpaid_abroad')
        cls.childcare = cls.env.ref('l10n_ua_hr_holidays.leave_type_childcare')
        for leave_type in (cls.basic, cls.hazard, cls.additional, cls.children, cls.sick,
                           cls.unpaid, cls.unpaid_abroad, cls.childcare):
            # Leaves are placed freely around the hire date here; the
            # six-month rule for the first annual leave is not under test.
            leave_type.write({
                'requires_experience': False,
                'leave_validation_type': 'hr',
            })

    def _employee(self, hire):
        employee = self.env['hr.employee'].create({
            'name': 'Entitlement Test %s' % hire,
            'hire_date': hire,
        })
        version = employee.with_context(active_test=False).version_ids[:1]
        if version:
            version.write({'contract_date_start': hire, 'contract_date_end': False})
        return employee

    def _balance(self, employee, leave_type, start, end, norm, **extra):
        vals = {
            'employee_id': employee.id,
            'leave_type_id': leave_type.id,
            'period_start': start,
            'period_end': end,
            'entitled_days': norm,
        }
        vals.update(extra)
        return self.env['hr.vacation.balance'].create(vals)

    def _leave(self, employee, leave_type, date_from, date_to):
        leave = self.env['hr.leave'].create({
            'name': 'Entitlement test leave',
            'employee_id': employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        })
        leave.action_approve()
        if leave.state != 'validate':
            leave._action_validate()
        self.assertEqual(leave.state, 'validate')
        return leave

    def _line(self, employee, as_of, leave_type):
        lines = [line for line in self.Entitlement._unused_vacation(employee, as_of)
                 if line['leave_type'] == leave_type]
        self.assertEqual(len(lines), 1, 'one line per leave type')
        return lines[0]

    # ------------------------------------------------------------------
    # Annual basic leave
    # ------------------------------------------------------------------

    def test_current_work_year_is_pro_rated(self):
        """The work year in progress gives its norm in proportion to the
        calendar days worked; the past ones give it in full, including the
        periods no balance was recorded for."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        line = self._line(employee, date(2026, 10, 16), self.basic)
        # 01.03.2026 – 16.10.2026 is 230 of the 365 days of the work year.
        self.assertAlmostEqual(line['accrued'], 24 + 24 + 24 * 230 / 365, places=4)
        self.assertEqual(days(line['remaining']), 64)
        current = [row for row in line['rows'] if row['is_current']]
        self.assertEqual(len(current), 1)
        self.assertAlmostEqual(current[0]['entitled'], 24, places=4)

    def test_short_period_proposed_norm_is_not_reduced_twice(self):
        """A balance shorter than a year gets the part of the yearly norm
        that falls on it (24 x 197 / 365 = 12.95 for 18.06 - 31.12), and the
        days earned in it are still those of the yearly norm: by 30.09,
        24 x 105 / 365 = 6.90, not reduced a second time."""
        employee = self._employee(date(2026, 6, 18))
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': employee.id,
            'leave_type_id': self.basic.id,
            'period_start': date(2026, 6, 18),
            'period_end': date(2026, 12, 31),
        })
        self.assertAlmostEqual(balance.entitled_days, round(24 * 197 / 365, 2), places=2)
        line = self._line(employee, date(2026, 9, 30), self.basic)
        self.assertAlmostEqual(line['accrued'], 24 * 105 / 365, places=2)

    def test_transfer_limits_do_not_forfeit_days(self):
        """Unused days of every past period are due, whatever the type
        carries over between periods."""
        employee = self._employee(date(2024, 3, 1))
        self.basic.write({'is_transferable': True, 'max_transfer_days': 5})
        self._balance(employee, self.basic, date(2024, 3, 1), date(2025, 2, 28), 24)
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        line = self._line(employee, date(2026, 2, 28), self.basic)
        self.assertEqual(days(line['remaining']), 48)

    def test_unpaid_leave_abroad_is_left_out_of_seniority(self):
        """Unpaid leave taken abroad or as an internally displaced person
        under martial law does not count towards the basic leave, even in a
        full past work year: 24 / 365 × 275 = 18.08."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        self._leave(employee, self.unpaid_abroad, date(2025, 5, 1), date(2025, 7, 29))
        line = self._line(employee, date(2026, 2, 28), self.basic)
        self.assertAlmostEqual(line['accrued'], 24 + 24 * 275 / 365, places=4)
        self.assertEqual(days(line['remaining']), 43)

    def test_ordinary_unpaid_leave_counts_as_seniority(self):
        """Unpaid leave agreed with the employer keeps the basic leave whole."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        self._leave(employee, self.unpaid, date(2025, 5, 1), date(2025, 7, 29))
        line = self._line(employee, date(2026, 2, 28), self.basic)
        self.assertEqual(days(line['remaining']), 48)

    def test_unpaid_leave_before_martial_law_counts_up_to_fifteen_days(self):
        """Before the limit was lifted only 15 days of unpaid leave a calendar
        year count as seniority: of 30 days in 2021, 15 are left out of the
        work year 01.03.2021 – 28.02.2022, 24 / 365 × 350 = 23.01."""
        employee = self._employee(date(2020, 3, 1))
        self._balance(employee, self.basic, date(2021, 3, 1), date(2022, 2, 28), 24)
        self._leave(employee, self.unpaid, date(2021, 6, 1), date(2021, 6, 30))
        line = self._line(employee, date(2022, 2, 28), self.basic)
        second = [row for row in line['rows'] if row['date_from'] == date(2021, 3, 1)][0]
        self.assertAlmostEqual(second['accrued'], 24 * 350 / 365, places=4)

    def test_childcare_leave_is_left_out_of_seniority(self):
        """The partly paid childcare leave does not count towards the basic
        leave, while sick leave does: a work year spent on childcare leave
        gives nothing."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        self._leave(employee, self.childcare, date(2025, 3, 1), date(2026, 2, 28))
        line = self._line(employee, date(2026, 2, 28), self.basic)
        self.assertEqual(days(line['remaining']), 24)

    def test_leave_past_the_date_counts_only_its_days_up_to_it(self):
        """A leave running past the date counts as used only up to it: 10
        of the 14 days by 10.06.2025, so 24 + 24 - 10 = 38 remain."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        self._leave(employee, self.basic, date(2025, 6, 1), date(2025, 6, 14))
        line = self._line(employee, date(2025, 6, 10), self.basic)
        self.assertEqual(line['used'], 10)

    def test_public_holidays_are_left_out_of_the_proportion(self):
        """With a holiday on the calendar, the year and the days worked are
        both counted without it."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self.env['resource.calendar.leaves'].create({
            'name': 'Test holiday',
            'date_from': datetime(2026, 5, 1, 8, 0),
            'date_to': datetime(2026, 5, 1, 16, 0),
            'resource_id': False,
            'company_id': employee.company_id.id,
        })
        line = self._line(employee, date(2026, 10, 16), self.basic)
        self.assertAlmostEqual(line['accrued'], 24 * 229 / 364, places=4)

    def test_days_used_go_against_the_oldest_period(self):
        """Used days are charged to the oldest right first."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2024, 3, 1), date(2025, 2, 28), 24)
        self._balance(employee, self.basic, date(2025, 3, 1), date(2026, 2, 28), 24)
        self._leave(employee, self.basic, date(2025, 6, 2), date(2025, 6, 29))
        line = self._line(employee, date(2026, 2, 28), self.basic)
        first, second = line['rows']
        self.assertAlmostEqual(first['used'], 24, places=4)
        self.assertAlmostEqual(first['remaining'], 0, places=4)
        self.assertAlmostEqual(second['used'], 4, places=4)
        self.assertAlmostEqual(second['remaining'], 20, places=4)
        self.assertEqual(days(line['remaining']), 20)

    def test_period_spanning_the_split_date_is_reported_in_two_parts(self):
        """A work year running into 2024 is split at 01.01.2024; the parts
        add up to the norm of the year."""
        employee = self._employee(date(2023, 7, 1))
        self._balance(employee, self.basic, date(2023, 7, 1), date(2024, 6, 30), 24)
        line = self._line(employee, date(2024, 6, 30), self.basic)
        self.assertEqual([row['is_split'] for row in line['rows']], [True, True])
        before, after = line['rows']
        self.assertEqual(before['date_to'], date(2023, 12, 31))
        self.assertEqual(after['date_from'], date(2024, 1, 1))
        # 184 and 182 of the 366 days of the work year.
        self.assertAlmostEqual(before['accrued'], 24 * 184 / 366, places=4)
        self.assertAlmostEqual(after['accrued'], 24 * 182 / 366, places=4)
        self.assertAlmostEqual(line['remaining_before_split'], 24 * 184 / 366, places=4)
        self.assertEqual(days(line['remaining']), 24)

    def test_usable_days_take_the_whole_current_period(self):
        """The days that may still be taken count the whole current work
        year, not only the part already worked."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        line = self._line(employee, date(2026, 4, 15), self.basic)
        self.assertEqual(days(line['usable']), 72)
        self.assertEqual(days(line['remaining']), 52)

    def test_first_work_year_is_pro_rated_before_six_months(self):
        """Before six months of the first work year only the days earned so
        far may be taken, not the whole year's leave."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        line = self._line(employee, date(2026, 5, 31), self.basic)
        # 92 of 365 days: 24 × 92 / 365 = 6.05, rounded up to 7.
        self.assertEqual(days(line['usable']), 7)
        self.assertEqual(days(line['remaining']), 7)
        self.assertTrue(line['pro_rated_first_year'])
        later = self._line(employee, date(2026, 9, 1), self.basic)
        self.assertEqual(days(later['usable']), 24)
        self.assertFalse(later['pro_rated_first_year'])

    # ------------------------------------------------------------------
    # Additional leave
    # ------------------------------------------------------------------

    def test_working_conditions_leave_leaves_out_sick_days(self):
        """The additional leave for working conditions is earned by the days
        actually worked; sick days do not count for it, while the basic
        leave keeps them."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self._balance(employee, self.hazard, date(2026, 3, 1), date(2027, 2, 28), 35)
        self._leave(employee, self.sick, date(2026, 4, 1), date(2026, 4, 10))
        as_of = date(2027, 2, 28)
        self.assertAlmostEqual(
            self._line(employee, as_of, self.hazard)['accrued'], 35 * 355 / 365, places=4)
        self.assertEqual(days(self._line(employee, as_of, self.basic)['remaining']), 24)

    def test_working_conditions_leave_counts_only_its_own_leave(self):
        """Of the absences, only the basic leave and the additional leave for
        working conditions count as seniority for the latter; another
        additional leave does not."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.hazard, date(2026, 3, 1), date(2027, 2, 28), 35)
        self._balance(employee, self.additional, date(2026, 3, 1), date(2027, 2, 28), 7)
        self._leave(employee, self.basic, date(2026, 4, 1), date(2026, 4, 14))
        self._leave(employee, self.additional, date(2026, 5, 4), date(2026, 5, 10))
        line = self._line(employee, date(2027, 2, 28), self.hazard)
        self.assertAlmostEqual(line['accrued'], 35 * 358 / 365, places=4)

    def test_overuse_of_one_type_does_not_reduce_another(self):
        """A negative basic leave balance does not eat into the additional
        leave."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self._balance(employee, self.hazard, date(2026, 3, 1), date(2027, 2, 28), 35)
        self._leave(employee, self.basic, date(2026, 4, 1), date(2026, 4, 24))
        as_of = date(2026, 6, 30)
        self.assertEqual(days(self._line(employee, as_of, self.basic)['remaining']), 0)
        # 122 of 365 days: 35 × 122 / 365 = 11.70.
        self.assertEqual(days(self._line(employee, as_of, self.hazard)['remaining']), 12)
        # The order's total: 0 + 11.70, rounded up once to 12.
        self.assertEqual(days(self.Entitlement._compensated_days(employee, as_of)), 12)

    def test_children_leave_is_granted_in_full(self):
        """The additional leave of workers with children is due in full for
        every calendar year with a day of seniority, not in proportion; a
        year spent entirely on childcare leave gives nothing."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.children, date(2024, 1, 1), date(2024, 12, 31), 10)
        self._balance(employee, self.children, date(2025, 1, 1), date(2025, 12, 31), 10)
        self._balance(employee, self.children, date(2026, 1, 1), date(2026, 12, 31), 10)
        self._leave(employee, self.childcare, date(2024, 3, 1), date(2024, 12, 31))
        line = self._line(employee, date(2026, 3, 15), self.children)
        self.assertEqual([row['accrued'] for row in line['rows']], [0.0, 10, 10])
        self.assertEqual(days(line['remaining']), 20)

    def test_overlapping_balances_are_counted_once(self):
        """A balance left from an earlier hire date that overlaps the current
        work year is not counted on top of it."""
        employee = self._employee(date(2026, 6, 18))
        self._balance(employee, self.basic, date(2026, 4, 14), date(2027, 4, 13), 24)
        self._balance(employee, self.basic, date(2026, 6, 18), date(2027, 6, 17), 24)
        line = self._line(employee, date(2026, 10, 18), self.basic)
        self.assertEqual(len(line['rows']), 1)
        self.assertEqual(line['rows'][0]['date_from'], date(2026, 6, 18))
        # 123 of 365 days: 24 × 123 / 365 = 8.09, rounded up to 9.
        self.assertEqual(days(line['remaining']), 9)

    def test_leave_not_paid_out_is_ignored(self):
        """Only the leave paid out on dismissal is counted."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self._leave(employee, self.unpaid, date(2026, 4, 1), date(2026, 4, 5))
        lines = self.Entitlement._unused_vacation(employee, date(2026, 6, 30))
        self.assertEqual([line['leave_type'] for line in lines], [self.basic])

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def test_dismissal_order_takes_the_days(self):
        """The dismissal order quotes the days as of the dismissal date."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        order = self.env['hr.order'].create({
            'order_type': 'dismissal',
            'date': date(2026, 10, 16),
            'date_dismissal': date(2026, 10, 16),
            'employee_id': employee.id,
            'subject': 'Dismissal',
        })
        # The order keeps the unrounded total; the phrase rounds it once.
        self.assertAlmostEqual(order.unused_vacation_days, 24 + 24 + 24 * 230 / 365, places=4)
        self.assertEqual(order.unused_vacation_days_phrase(), '64 календарні дні')

    def test_future_period_is_not_counted(self):
        """A balance of a period starting after the date asked for adds
        nothing."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self._balance(employee, self.basic, date(2027, 3, 1), date(2028, 2, 29), 24)
        line = self._line(employee, date(2026, 10, 16), self.basic)
        self.assertEqual(days(line['remaining']), 64)
        self.assertTrue(all(row['date_from'] <= date(2026, 10, 16) for row in line['rows']))

    def _dismissal_order(self, employee, dismissal_date):
        return self.env['hr.order'].create({
            'order_type': 'dismissal',
            'date': dismissal_date,
            'date_dismissal': dismissal_date,
            'employee_id': employee.id,
            'subject': 'Dismissal',
        })

    def test_order_rounds_the_total_once(self):
        """The order rounds the total of all leave types once: 1.38 basic +
        0.40 additional = 1.78 -> 2 days, not 2 + 1 = 3 from rounding each
        type up."""
        employee = self._employee(date(2026, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        self._balance(employee, self.additional, date(2026, 3, 1), date(2027, 2, 28), 7)
        order = self._dismissal_order(employee, date(2026, 3, 21))
        self.assertAlmostEqual(order.unused_vacation_days, 31 * 21 / 365, places=4)
        self.assertEqual(order.unused_vacation_days_phrase(), '2 календарні дні')

    def test_manual_day_count_on_the_order_is_kept(self):
        """A day count typed over the computed one stays while the employee
        and the dismissal date stay the same."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        order = self._dismissal_order(employee, date(2026, 10, 16))
        # The order keeps the unrounded total; the phrase rounds it once.
        self.assertAlmostEqual(order.unused_vacation_days, 24 + 24 + 24 * 230 / 365, places=4)
        order.unused_vacation_days = 5
        order.subject = 'Dismissal (corrected)'
        self.assertEqual(order.unused_vacation_days, 5)

    def test_computed_days_reach_the_loaded_template(self):
        """Loading the dismissal template quotes the computed day count."""
        employee = self._employee(date(2024, 3, 1))
        self._balance(employee, self.basic, date(2026, 3, 1), date(2027, 2, 28), 24)
        order = self._dismissal_order(employee, date(2026, 10, 16))
        wizard = self.env['hr.order.template.wizard'].create({
            'order_id': order.id,
            'order_type': order.order_type,
            'template_id': self.env.ref('l10n_ua_hr_documents.order_template_dismissal').id,
        })
        wizard.action_apply_template()
        text = ' '.join(re.sub(r'<[^>]+>', ' ', order.content or '').split())
        self.assertIn('виплатити компенсацію за 64 календарні дні', text)

@tagged('post_install', '-at_install')
class TestLeaveTypeImportCategories(TransactionCase):
    """The company's import button and the migration of the types it made."""

    def test_import_sets_specific_categories(self):
        company = self.env['res.company'].create({'name': 'Import Categories Co'})
        company.action_import_ua_leave_types()
        types = self.env['hr.leave.type'].search([('company_id', '=', company.id)])
        by_name = {t.name: t.ua_leave_category for t in types}
        self.assertEqual(by_name['Соціальна відпустка (на дітей)'], 'social_children')
        self.assertEqual(by_name['Додаткова чорнобильцям'], 'chornobyl')
        self.assertEqual(by_name['Додаткова ветеранам війни'], 'veteran')
        self.assertEqual(by_name['Додаткова за шкідливі умови праці'], 'annual_hazardous')
        self.assertEqual(by_name['Додаткова за ненормований робочий день'], 'annual_irregular')
        self.assertEqual(by_name['Додаткова за особливий характер праці'], 'annual_special')
        self.assertIn('unpaid_abroad', by_name.values())
        self.assertIn('unpaid_childcare', by_name.values())

    def _migration(self):
        path = os.path.join(
            os.path.dirname(__file__), '..', 'migrations', '19.0.1.2.2',
            'post-migration.py')
        spec = importlib.util.spec_from_file_location(
            'l10n_ua_hr_holidays_19_1_2_2_post', path)
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        return script

    def test_migration_moves_only_untouched_imported_types(self):
        script = self._migration()
        company = self.env.company
        LeaveType = self.env['hr.leave.type']
        imported = LeaveType.create({
            'name': 'Соціальна відпустка (на дітей)',
            'ua_leave_category': 'social',
            'company_id': company.id,
        })
        renamed = LeaveType.create({
            'name': 'Відпустка на дітей (власна)',
            'ua_leave_category': 'social',
            'company_id': company.id,
        })
        recategorised = LeaveType.create({
            'name': 'Додаткова за шкідливі умови праці',
            'ua_leave_category': 'other',
            'company_id': company.id,
        })
        self.env.flush_all()
        script.migrate(self.env.cr, '19.0.1.1.2')
        (imported | renamed | recategorised).invalidate_recordset(['ua_leave_category'])
        self.assertEqual(imported.ua_leave_category, 'social_children')
        self.assertEqual(renamed.ua_leave_category, 'social')
        self.assertEqual(recategorised.ua_leave_category, 'other')

    def test_migration_moves_the_shared_types(self):
        """The module's shared types carried the generic categories before
        their data file was corrected; the data file is never reloaded, so
        the migration moves them by external id."""
        script = self._migration()
        children = self.env.ref('l10n_ua_hr_holidays.leave_type_social_children')
        hazard = self.env.ref('l10n_ua_hr_holidays.leave_type_additional_hazard')
        children.ua_leave_category = 'social'
        hazard.ua_leave_category = 'annual_additional'
        self.env.flush_all()
        script.migrate(self.env.cr, '19.0.1.1.2')
        (children | hazard).invalidate_recordset(['ua_leave_category'])
        self.assertEqual(children.ua_leave_category, 'social_children')
        self.assertEqual(hazard.ua_leave_category, 'annual_hazardous')

    def test_migration_recounts_draft_dismissal_orders(self):
        """A draft dismissal order gets its days recounted by the new rule,
        with a note in its history; a confirmed one keeps its figure."""
        script = self._migration()
        # Public holidays are working days under martial law.
        self.env['resource.calendar.leaves'].search([('resource_id', '=', False)]).unlink()
        employee = self.env['hr.employee'].create({
            'name': 'Migration Recount Employee',
            'hire_date': date(2024, 3, 1),
        })
        self.env['hr.vacation.balance'].create({
            'employee_id': employee.id,
            'leave_type_id': self.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic').id,
            'period_start': date(2026, 3, 1),
            'period_end': date(2027, 2, 28),
            'entitled_days': 24,
        })
        Order = self.env['hr.order']
        vals = {
            'order_type': 'dismissal',
            'date': date(2026, 10, 16),
            'date_dismissal': date(2026, 10, 16),
            'employee_id': employee.id,
            'subject': 'Dismissal',
        }
        draft = Order.create(vals)
        confirmed = Order.create(vals)
        # The figure the old rule left on both.
        draft.unused_vacation_days = 72
        confirmed.unused_vacation_days = 72
        confirmed.state = 'confirmed'
        messages = len(draft.message_ids)
        self.env.flush_all()
        script.migrate(self.env.cr, '19.0.1.1.2')
        self.env.invalidate_all()
        self.assertAlmostEqual(draft.unused_vacation_days, 24 + 24 + 24 * 230 / 365, places=4)
        self.assertEqual(len(draft.message_ids), messages + 1)
        self.assertEqual(confirmed.unused_vacation_days, 72)
