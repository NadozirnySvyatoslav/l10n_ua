"""A change of the public holiday list reaches the leaves already entered (#344).

Public holidays are not counted in the duration of a leave counted in
calendar days (art. 5 of the Law "On Leaves", art. 73 of the Labour Code).
Under martial law they are working days, and the list may be emptied, so it
changes after leaves are entered.
"""
from datetime import date, datetime

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHolidayRecount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Chatter notes are checked in English, whatever language is loaded.
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        cls.company = cls.env.company
        cls.company.resource_calendar_id.tz = 'Europe/Kyiv'
        cls.Holiday = cls.env['resource.calendar.leaves']
        # July 2025 without holidays: the test adds its own.
        cls.Holiday.search([
            ('resource_id', '=', False),
            ('date_from', '<=', '2025-08-01 00:00:00'),
            ('date_to', '>=', '2025-06-30 00:00:00'),
        ]).unlink()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Holiday Recount Employee',
            'company_id': cls.company.id,
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Annual Leave (Holiday Recount Test)',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
            'requires_experience': False,
            'company_id': cls.company.id,
        })

    def _leave(self, date_from, date_to, **vals):
        leave = self.env['hr.leave'].create({
            'name': 'Vacation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
            **vals,
        })
        # Stored as a leave entered earlier would be.
        leave.flush_recordset()
        return leave

    def _holiday(self, day, **vals):
        return self.Holiday.create({
            'name': 'Holiday (recount test)',
            'date_from': datetime.combine(day, datetime.min.time()),
            'date_to': datetime(day.year, day.month, day.day, 23, 59, 59),
            **vals,
        })

    def _durations(self, leave):
        return (leave.calendar_days, leave.number_of_days, leave.working_days)

    def _notes(self, leave):
        return leave.message_ids.filtered(lambda m: 'recounted' in (m.body or ''))

    def test_a_holiday_added_removed_and_moved_reaches_a_draft(self):
        # Monday 14 - Sunday 20 July 2025: 7 days, 5 weekdays.
        leave = self._leave(date(2025, 7, 14), date(2025, 7, 20))
        self.assertEqual(self._durations(leave), (7, 7, 5))

        holiday = self._holiday(date(2025, 7, 16))
        self.assertEqual(self._durations(leave), (6, 6, 4))
        self.assertEqual(len(self._notes(leave)), 1)

        holiday.write({'date_from': datetime(2025, 7, 25, 0, 0),
                       'date_to': datetime(2025, 7, 25, 23, 59, 59)})
        self.assertEqual(self._durations(leave), (7, 7, 5))

        holiday.write({'date_from': datetime(2025, 7, 17, 0, 0),
                       'date_to': datetime(2025, 7, 17, 23, 59, 59)})
        self.assertEqual(self._durations(leave), (6, 6, 4))

        # An empty list is a valid setup: under martial law holidays are
        # working days.
        holiday.unlink()
        self.assertEqual(self._durations(leave), (7, 7, 5))
        self.assertEqual(len(self._notes(leave)), 4)

    def test_two_leaves_of_one_period_agree_whenever_the_holiday_came(self):
        before = self._leave(date(2025, 7, 14), date(2025, 7, 20))
        self._holiday(date(2025, 7, 16))
        other = self.env['hr.employee'].create({
            'name': 'Holiday Recount Other', 'company_id': self.company.id})
        after = self._leave(date(2025, 7, 14), date(2025, 7, 20),
                            employee_id=other.id)
        self.assertEqual(self._durations(before), self._durations(after))

    def test_an_approved_leave_is_recounted_and_flagged(self):
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'entitled_days': 24,
            'company_id': self.company.id,
        })
        leave = self._leave(date(2025, 7, 14), date(2025, 7, 20),
                            vacation_balance_id=balance.id,
                            average_daily_salary=1000.0)
        later = self._leave(date(2025, 8, 4), date(2025, 8, 10),
                            vacation_balance_id=balance.id)
        leave._action_validate()
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(leave.remaining_days_after, 17)
        self.assertEqual(later.remaining_days_before, 17)
        self.assertEqual(balance.used_days, 7)

        self._holiday(date(2025, 7, 16))
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(self._durations(leave), (6, 6, 4))
        self.assertEqual(leave.vacation_pay_amount, 6000.0)
        self.assertEqual(leave.remaining_days_after, 18)
        # A leave after it in the period, though off the holiday, follows.
        self.assertEqual(later.remaining_days_before, 18)
        self.assertEqual(balance.used_days, 6)
        note = self._notes(leave)
        self.assertEqual(len(note), 1)
        self.assertIn('already approved', note.body)
        self.assertIn('calendar days 7 → 6', note.body)
        self.assertIn('working days 5 → 4', note.body)
        self.assertIn('Vacation pay 7000.0 → 6000.0', note.body)
        # The later leave's own duration did not move: no note on it.
        self.assertFalse(self._notes(later))

    def test_only_leaves_of_the_holiday_dates_and_company_are_touched(self):
        far = self._leave(date(2025, 7, 1), date(2025, 7, 6))
        other_company = self.env['res.company'].create(
            {'name': 'Holiday Recount Other Company'})
        stranger = self.env['hr.employee'].create({
            'name': 'Holiday Recount Stranger',
            'company_id': other_company.id,
        })
        other_type = self.leave_type.copy({'company_id': other_company.id})
        foreign = self.env['hr.leave'].with_company(other_company).create({
            'name': 'Vacation', 'employee_id': stranger.id,
            'holiday_status_id': other_type.id,
            'request_date_from': date(2025, 7, 14),
            'request_date_to': date(2025, 7, 20),
        })
        self.assertEqual(foreign.calendar_days, 7)
        self.assertEqual(self.env['hr.leave']._l10n_ua_leaves_on_holidays([{
            'company_id': self.company.id,
            'date_from': datetime(2025, 7, 16), 'date_to': datetime(2025, 7, 16, 23, 59, 59),
        }]) & (far | foreign), self.env['hr.leave'])

        self._holiday(date(2025, 7, 16))
        self.assertEqual(foreign.calendar_days, 7)
        self.assertEqual(far.calendar_days, 6)
        self.assertFalse(self._notes(far) | self._notes(foreign))

    def test_a_holiday_entered_in_local_time_is_one_day(self):
        # Entered in Kyiv time, 16 July starts on 15 July at 21:00 UTC.
        leave = self._leave(date(2025, 7, 14), date(2025, 7, 20))
        self.Holiday.create({
            'name': 'Local holiday',
            'date_from': '2025-07-15 21:00:00', 'date_to': '2025-07-16 20:59:59',
        })
        self.assertEqual(self._durations(leave), (6, 6, 4))
