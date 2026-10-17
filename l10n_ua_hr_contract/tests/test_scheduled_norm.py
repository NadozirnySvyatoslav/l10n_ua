"""Тести норми робочого часу версії на базі штатного календаря (#213).

Ключовий тест — test_leave_and_payroll_agree_on_daily_norm: до цієї зміни
відпустки списували 8 год/день зі штатного календаря, а зарплата рахувала
7,2 год/день з UA-графіка для того самого працівника.
"""

from odoo.tests import tagged

from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestScheduledNorm(ContractTestCase):

    def _version_with_calendar(self, xmlid, **kwargs):
        calendar = self.env.ref('l10n_ua_hr_contract.%s' % xmlid)
        return self._create_version(resource_calendar_id=calendar.id, **kwargs)

    def test_norm_from_calendar_full_rate(self):
        """STD40 + повна ставка → 40 год/тиждень, 8 год/день."""
        version = self._version_with_calendar(
            'resource_calendar_ua_std40', work_rate=1.0)
        self.assertAlmostEqual(version.scheduled_hours_week, 40.0, places=2)
        self.assertAlmostEqual(version.scheduled_hours_day, 8.0, places=2)

    def test_norm_scaled_by_work_rate(self):
        """STD40 + 0.5 ставки → 20 год/тиждень, 4 год/день (#149)."""
        version = self._version_with_calendar(
            'resource_calendar_ua_std40', work_rate=0.5)
        self.assertAlmostEqual(version.scheduled_hours_week, 20.0, places=2)
        self.assertAlmostEqual(version.scheduled_hours_day, 4.0, places=2)

    def test_norm_reduced_schedule(self):
        """STD36 → 36 год/тиждень, 7,2 год/день."""
        version = self._version_with_calendar(
            'resource_calendar_ua_std36', work_rate=1.0)
        self.assertAlmostEqual(version.scheduled_hours_week, 36.0, places=2)
        self.assertAlmostEqual(version.scheduled_hours_day, 7.2, places=2)

    def test_norm_falls_back_without_calendar(self):
        """Без календаря → 40 год/тиждень, 8 год/день, без traceback."""
        version = self._create_version(work_rate=1.0)
        version.resource_calendar_id = False
        self.assertAlmostEqual(version.scheduled_hours_week, 40.0, places=2)
        self.assertAlmostEqual(version.scheduled_hours_day, 8.0, places=2)

    def test_norm_empty_attendance_calendar_guarded(self):
        """Календар без інтервалів не дає мовчки нульову норму."""
        calendar = self.env['resource.calendar'].create({
            'name': 'Порожній графік',
            'company_id': self.company.id,
            'attendance_ids': [(5, 0, 0)],
        })
        version = self._create_version(
            work_rate=1.0, resource_calendar_id=calendar.id)
        self.assertGreater(version.scheduled_hours_week, 0.0)
        self.assertGreater(version.scheduled_hours_day, 0.0)

    def test_shift_calendar_keeps_explicit_norm(self):
        """Змінний 2/2 без тижневої сітки зберігає явну норму 42/12."""
        version = self._version_with_calendar(
            'resource_calendar_ua_shift2x2', work_rate=1.0)
        self.assertAlmostEqual(version.scheduled_hours_week, 42.0, places=2)
        self.assertAlmostEqual(version.scheduled_hours_day, 12.0, places=2)

    def test_norm_follows_calendar_change(self):
        """Зміна календаря версії перераховує норму."""
        version = self._version_with_calendar(
            'resource_calendar_ua_std40', work_rate=1.0)
        self.assertAlmostEqual(version.scheduled_hours_day, 8.0, places=2)
        version.resource_calendar_id = self.env.ref(
            'l10n_ua_hr_contract.resource_calendar_ua_std36')
        self.assertAlmostEqual(version.scheduled_hours_day, 7.2, places=2)

    def test_leave_and_payroll_agree_on_daily_norm(self):
        """A 36-hour schedule must give payroll and leave the same daily norm."""
        calendar = self.env.ref(
            'l10n_ua_hr_contract.resource_calendar_ua_std36')
        version = self._create_version(
            work_rate=1.0, resource_calendar_id=calendar.id)
        self.assertAlmostEqual(version.scheduled_hours_day, 7.2, places=2)
        self.assertAlmostEqual(
            version.scheduled_hours_day,
            version.resource_calendar_id.hours_per_day,
            places=2,
            msg='Payroll norm diverged from the calendar leave is deducted from')

    def test_scheduled_hours_of_a_working_day(self):
        """The planned day takes the part-time from one source only."""
        self.assertEqual(self.company.resource_calendar_id.hours_per_week, 40.0)
        cases = [
            ('resource_calendar_ua_std40', 1.0, 8.0),
            ('resource_calendar_ua_std40', 0.5, 4.0),
            # A shorter schedule says the part-time itself, whatever the rate.
            ('resource_calendar_ua_part20', 1.0, 4.0),
            ('resource_calendar_ua_part20', 0.5, 4.0),
            # A reduced working time is the whole day of the employee.
            ('resource_calendar_ua_std36', 1.0, 7.2),
            # A shift is not a roster: the day of the company at the rate.
            ('resource_calendar_ua_shift2x2', 1.0, 8.0),
            ('resource_calendar_ua_shift1x3', 0.5, 4.0),
        ]
        for xmlid, rate, hours in cases:
            with self.subTest(schedule=xmlid, rate=rate):
                version = self._version_with_calendar(xmlid, work_rate=rate)
                self.assertAlmostEqual(
                    version._l10n_ua_scheduled_hours(self.company, 8.0), hours, places=2)

    def test_norm_hours_of_a_working_day(self):
        """Only a reduced working time shortens the day of the norm."""
        std36 = self._version_with_calendar('resource_calendar_ua_std36')
        part20 = self._version_with_calendar('resource_calendar_ua_part20')
        self.assertAlmostEqual(std36._l10n_ua_norm_hours(8.0), 7.2, places=2)
        self.assertAlmostEqual(part20._l10n_ua_norm_hours(8.0), 8.0, places=2)
        # A short day of the production calendar stays short.
        self.assertAlmostEqual(part20._l10n_ua_norm_hours(7.0), 7.0, places=2)
