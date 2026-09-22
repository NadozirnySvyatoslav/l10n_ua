"""Тести експорту військового обліку до ТЦК (#156)."""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestMilitaryTcc(TestHrUaBase):

    def _military_employee(self):
        return self._create_employee(
            name='Військовий Іван',
            rnokpp=self.get_unique_rnokpp(),
            birthday=date(1990, 5, 20),
            military_register_category='liable',
            military_specialty='100',
            military_document_number='АА123456')

    def test_export_military_csv(self):
        emp = self._military_employee()
        report = self.env['hr.employee.military.report'].create({
            'company_id': self.company.id, 'date': date(2026, 1, 31)})
        report.write({'employee_ids': [(6, 0, emp.ids)], 'state': 'generated'})
        report.action_export_csv()
        self.assertTrue(report.export_data)
        self.assertTrue(report.export_filename.endswith('.csv'))
        text = report.export_data.content.decode('cp1251')
        self.assertIn('РНОКПП', text)
        self.assertIn(emp.rnokpp, text)
        self.assertIn('Військовий Іван', text)
        report_action = self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_military_form5')
        html, _content_type = report_action._render_qweb_html(
            report_action.report_name, report.ids)
        self.assertIn('СПИСКИ', html.decode())

    def test_notification_submit(self):
        emp = self._military_employee()
        notif = self.env['hr.military.notification'].create({
            'notification_type': 'hire',
            'employee_id': emp.id,
            'event_date': date(2026, 1, 15),
        })
        self.assertTrue(notif.name.startswith('ТЦК/'))
        self.assertEqual(notif.state, 'draft')
        notif.action_submit()
        self.assertEqual(notif.state, 'submitted')
        self.assertEqual(notif.snapshot_rnokpp, emp.rnokpp)
        self.assertTrue(notif.submitted_date)
        # Файл повідомлення сформовано і містить реквізити.
        text = notif.export_data.content.decode('cp1251')
        self.assertIn('Прийняття на роботу', text)
        self.assertIn(emp.rnokpp, text)

    def test_notification_type_dismissal(self):
        emp = self._military_employee()
        notif = self.env['hr.military.notification'].create({
            'notification_type': 'dismissal', 'employee_id': emp.id})
        notif.action_submit()
        text = notif.export_data.content.decode('cp1251')
        self.assertIn('Звільнення', text)

    def test_form5_groups_follow_paragraph_36(self):
        officer_rank = self.env['hr.military.rank'].create({
            'name': 'Test Officer',
            'code': 'TEST-OFFICER',
            'category': 'officer',
        })
        officer = self._create_employee(
            name='Officer', gender='male',
            military_register_category='liable',
            military_rank_id=officer_rank.id)
        woman = self._create_employee(
            name='Woman', gender='female',
            military_register_category='reservist',
            military_rank_id=officer_rank.id)
        conscript = self._create_employee(
            name='Conscript', gender='female',
            military_register_category='conscript')
        soldier = self._create_employee(
            name='Soldier', gender='male',
            military_register_category='liable')

        self.assertEqual(officer.military_list_group, 'officers')
        self.assertEqual(woman.military_list_group, 'women')
        self.assertEqual(conscript.military_list_group, 'conscripts')
        self.assertEqual(soldier.military_list_group, 'soldiers')

    def test_notification_deadlines(self):
        emp = self._military_employee()
        hired = self.env['hr.military.notification'].create({
            'notification_type': 'hire',
            'employee_id': emp.id,
            'event_date': date(2026, 1, 15),
        })
        changed = self.env['hr.military.notification'].create({
            'notification_type': 'data_change',
            'employee_id': emp.id,
            'event_date': date(2026, 8, 24),
        })

        self.assertEqual(hired.deadline_date, date(2026, 1, 22))
        self.assertEqual(changed.deadline_date, date(2026, 9, 5))
        hired.action_submit()
        self.assertFalse(hired.is_overdue)

    def test_age_exclusion_uses_rank_limit(self):
        today = date.today()
        regular = self._create_employee(
            name='Regular Reserve',
            birthday=today - relativedelta(years=60),
            military_register_category='liable')
        general_rank = self.env['hr.military.rank'].create({
            'name': 'Test General',
            'code': 'TEST-GENERAL',
            'category': 'general',
        })
        young_general = self._create_employee(
            name='Young General',
            birthday=today - relativedelta(years=60),
            military_register_category='liable',
            military_rank_id=general_rank.id)
        old_general = self._create_employee(
            name='Old General',
            birthday=today - relativedelta(years=65),
            military_register_category='reservist',
            military_rank_id=general_rank.id)

        self.env['hr.employee']._cron_mark_military_age_excluded()

        self.assertEqual(regular.military_exclusion_mark, 'age')
        self.assertEqual(regular.military_exclusion_date, today)
        self.assertFalse(young_general.military_exclusion_mark)
        self.assertEqual(old_general.military_exclusion_mark, 'age')
        self.assertEqual(old_general.military_exclusion_date, today)
