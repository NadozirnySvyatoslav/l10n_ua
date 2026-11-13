"""#524 — ліміт бронювання за Порядком № 76 у редакції ПКМУ № 1328."""
from datetime import date, timedelta

from odoo.tests import tagged

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestReservationLimit(TestHrUaBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref('l10n_ua_hr_base.group_hr_ua_officer')
        cls.officer_user = cls.env['res.users'].create({
            'name': 'Військовий облік', 'login': 'reservation_officer_524',
            'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])],
            'group_ids': [(4, group.id)],
        })
        cls.officer = cls.env['hr.employee'].create({
            'name': 'Відповідальний ВО', 'company_id': cls.company.id,
            'user_id': cls.officer_user.id,
        })
        cls.company.write({
            'military_officer_id': cls.officer.id,
            'l10n_ua_critical_enterprise': True,
            'l10n_ua_reservation_limit': 50.0,
        })

    def _liable(self, reserved=False, **vals):
        vals.setdefault('military_reservation_until',
                        date.today() + timedelta(days=90) if reserved else False)
        return self._create_employee(
            military_register_category='liable', military_reservation=reserved, **vals)

    def _reminders(self, needle):
        return self.officer.activity_ids.filtered(lambda a: needle in (a.summary or ''))

    def test_share_counts_liable_only(self):
        self._liable(reserved=True)
        self._liable()
        self._create_employee(military_register_category='conscript')
        self._liable(reserved=True, military_reservation_until=date.today() - timedelta(days=1))
        self.company.invalidate_recordset()
        self.assertEqual(self.company.l10n_ua_liable_count, 3)
        self.assertEqual(self.company.l10n_ua_reserved_count, 1)
        self.assertAlmostEqual(self.company.l10n_ua_reservation_share, 100 / 3, places=2)
        self.assertFalse(self.company.l10n_ua_reservation_exceeded)

    def test_base_from_ministry_decision(self):
        self.company.write({'l10n_ua_reservation_base': 10, 'l10n_ua_reservation_limit': 95.0})
        for _i in range(3):
            self._liable(reserved=True)
        self.company.invalidate_recordset()
        self.assertAlmostEqual(self.company.l10n_ua_reservation_share, 30.0)
        self.assertFalse(self.company.l10n_ua_reservation_exceeded)

    def test_exceeded_creates_one_reminder_with_working_day_deadline(self):
        self._liable(reserved=True)
        self._liable(reserved=True)
        self._liable()
        self.company.invalidate_recordset()
        self.assertTrue(self.company.l10n_ua_reservation_exceeded)
        today = date(2026, 11, 3)  # вівторок
        self.company._l10n_ua_check_reservation(today)
        self.company._l10n_ua_check_reservation(today)
        reminder = self._reminders('Перевищено ліміт')
        self.assertEqual(len(reminder), 1)
        self.assertEqual(reminder.user_id, self.officer_user)
        # Службовий строк 5 р. д.: 03.11 (вт) → 10.11 (вт).
        self.assertEqual(reminder.date_deadline, date(2026, 11, 10))
        # К1 (#524): у ПКМУ № 1328 немає «п. 9-2» і 10 р. д. на анулювання.
        self.assertNotIn('9-2', reminder.note)
        self.assertNotIn('10 робочих', reminder.note)
        self.assertIn('ПКМУ № 1328', reminder.note)

    def test_not_critical_never_exceeded(self):
        self.company.l10n_ua_critical_enterprise = False
        self._liable(reserved=True)
        self.company.invalidate_recordset()
        self.assertFalse(self.company.l10n_ua_reservation_exceeded)

    def test_increased_limit_end_reminds_once(self):
        until = date(2026, 12, 8)
        self.company.l10n_ua_reservation_limit_until = until
        self.company._l10n_ua_check_reservation(date(2026, 12, 7))
        self.assertFalse(self._reminders('збільшений ліміт'))
        self.company._l10n_ua_check_reservation(date(2026, 12, 9))
        reminder = self._reminders('збільшений ліміт')
        self.assertEqual(len(reminder), 1)
        self.assertEqual(self.company.l10n_ua_limit_end_notified, until)
        reminder.action_feedback()
        self.company._l10n_ua_check_reservation(date(2026, 12, 10))
        self.assertFalse(self._reminders('збільшений ліміт'))

    def test_critical_status_end_warns_in_advance(self):
        self.company.l10n_ua_critical_until = date(2026, 12, 31)
        self.company._l10n_ua_check_reservation(date(2026, 11, 3))
        self.assertFalse(self._reminders('статус критичності'))
        self.company._l10n_ua_check_reservation(date(2026, 12, 5))
        self.assertEqual(self._reminders('статус критичності').date_deadline,
                         date(2026, 12, 31))

    def test_onchange_authority(self):
        company = self.env['res.company'].new({'l10n_ua_critical_authority': 'mod'})
        company._onchange_l10n_ua_critical_authority()
        self.assertEqual(company.l10n_ua_reservation_limit, 95.0)

    def test_limit_range_constraint(self):
        with self.assertRaises(Exception), self.cr.savepoint():
            self.company.l10n_ua_reservation_limit = 120
            self.company.flush_recordset()

    def test_cron_runs(self):
        self._liable(reserved=True)
        self.env['res.company']._cron_check_reservation_limits()
        self.assertTrue(self._reminders('Перевищено ліміт'))
