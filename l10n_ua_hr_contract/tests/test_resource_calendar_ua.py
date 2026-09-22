"""Тести UA-атрибутів на штатному resource.calendar (#213).

Покриття:
- Тижнева норма рахується ядром із рядків присутності (без UA-дубліката)
- Скорочений і двотижневий графіки
- Порожній календар не падає
- UA-атрибути зберігаються
- Усі десять передвизначених календарів завантажено
"""

from odoo.tests import tagged

from .common import ContractTestCase

UA_CALENDAR_CODES = [
    'STD40', 'STD36', 'STD24', 'PART20', 'STD6D',
    'FLEX', 'SHIFT2X2', 'SHIFT1X3', 'SHIFT3X3', 'SUMM',
]


@tagged('post_install', '-at_install')
class TestResourceCalendarUa(ContractTestCase):

    def _calendar(self, **kwargs):
        vals = {
            'name': 'Тестовий календар',
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['resource.calendar'].create(vals)

    @staticmethod
    def _week(hour_from, hour_to, days=5, period='morning'):
        # Odoo 20 dropped resource.calendar.attendance.name and week_type
        # (multi-week rotations are a 'variable' calendar now).
        return [
            (0, 0, {
                'dayofweek': str(day),
                'day_period': period,
                'hour_from': hour_from,
                'hour_to': hour_to,
            })
            for day in range(days)
        ]

    def test_hours_per_week_from_attendances(self):
        """40 год/тиждень рахуються з рядків присутності самим ядром."""
        calendar = self._calendar(attendance_ids=[(5, 0, 0)]
                                  + self._week(9.0, 13.0)
                                  + self._week(14.0, 18.0, period='afternoon'))
        self.assertAlmostEqual(calendar.hours_per_week, 40.0, places=2)
        self.assertAlmostEqual(calendar.hours_per_day, 8.0, places=2)

    def test_hours_per_week_reduced_schedule(self):
        """Скорочений графік дає 36 год і несе ознаку ua_reduced_hours."""
        calendar = self._calendar(
            ua_reduced_hours=True,
            attendance_ids=[(5, 0, 0)]
            + self._week(9.0, 13.0)
            + self._week(14.0, 17.2, period='afternoon'))
        self.assertAlmostEqual(calendar.hours_per_week, 36.0, places=2)
        self.assertAlmostEqual(calendar.hours_per_day, 7.2, places=2)
        self.assertTrue(calendar.ua_reduced_hours)

    def test_hours_per_week_variable_calendar_is_user_set(self):
        """Багатотижневу ротацію Odoo 20 описує календарем calendar_type
        'variable': норму тижня там задає користувач, ядро її не перераховує
        з рядків присутності, і наш код має читати саме задане значення."""
        calendar = self._calendar(
            calendar_type='variable',
            hours_per_week=40.0,
            attendance_ids=[(5, 0, 0)] + self._week(9.0, 17.0))
        self.assertAlmostEqual(calendar.hours_per_week, 40.0, places=2)

    def test_hours_per_week_empty_calendar(self):
        """Календар без інтервалів дає 0.0 і не падає."""
        calendar = self._calendar(attendance_ids=[(5, 0, 0)])
        self.assertAlmostEqual(calendar.hours_per_week, 0.0, places=2)
        self.assertAlmostEqual(calendar.hours_per_day, 0.0, places=2)

    def test_ua_attributes_persist(self):
        """UA-атрибути зберігаються й читаються назад."""
        calendar = self._calendar(
            ua_code='TESTNIGHT',
            ua_schedule_type='shift',
            ua_is_night_work=True,
            ua_night_start_hour=21.0,
            ua_night_end_hour=5.0,
            ua_is_hazardous=True,
        )
        calendar.invalidate_recordset()
        self.assertEqual(calendar.ua_code, 'TESTNIGHT')
        self.assertEqual(calendar.ua_schedule_type, 'shift')
        self.assertTrue(calendar.ua_is_night_work)
        self.assertAlmostEqual(calendar.ua_night_start_hour, 21.0)
        self.assertAlmostEqual(calendar.ua_night_end_hour, 5.0)
        self.assertTrue(calendar.ua_is_hazardous)

    def test_predefined_calendars_loaded(self):
        """Усі десять передвизначених графіків існують як resource.calendar."""
        for code in UA_CALENDAR_CODES:
            xmlid = 'l10n_ua_hr_contract.resource_calendar_ua_%s' % code.lower()
            calendar = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(calendar, 'Missing predefined calendar %s' % xmlid)
            self.assertEqual(calendar.ua_code, code)

    def test_predefined_calendars_have_a_norm(self):
        """Жоден передвизначений графік не дає нульової норми."""
        for code in UA_CALENDAR_CODES:
            xmlid = 'l10n_ua_hr_contract.resource_calendar_ua_%s' % code.lower()
            calendar = self.env.ref(xmlid)
            self.assertGreater(
                calendar.hours_per_week, 0.0,
                'Calendar %s has a zero weekly norm' % code)
            self.assertGreater(
                calendar.hours_per_day, 0.0,
                'Calendar %s has a zero daily norm' % code)

    def test_predefined_weekly_norms(self):
        """Норми передвизначених графіків збігаються зі старими hr.work.schedule."""
        expected = {
            'std40': (40.0, 8.0),
            'std36': (36.0, 7.2),
            'std24': (24.0, 4.8),
            'part20': (20.0, 4.0),
            'std6d': (40.0, 6.67),
            'flex': (40.0, 8.0),
            'shift2x2': (42.0, 12.0),
            'shift1x3': (42.0, 24.0),
            'shift3x3': (28.0, 8.0),
            'summ': (40.0, 8.0),
        }
        for suffix, (week, day) in expected.items():
            calendar = self.env.ref(
                'l10n_ua_hr_contract.resource_calendar_ua_%s' % suffix)
            self.assertAlmostEqual(
                calendar.hours_per_week, week, places=1,
                msg='Weekly norm changed for %s' % suffix)
            self.assertAlmostEqual(
                calendar.hours_per_day, day, places=1,
                msg='Daily norm changed for %s' % suffix)
