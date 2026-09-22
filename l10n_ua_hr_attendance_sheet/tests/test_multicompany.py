"""Multi-company record-rule presence (issue #178).

Плюс перевірка, що табель не створюється в компанії, вимкненій
у перемикачі компаній.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAttendanceSheetMultiCompany(TransactionCase):

    def test_rules_exist_and_are_global(self):
        refs = [
            'l10n_ua_hr_attendance_sheet.hr_timesheet_company_rule',
            'l10n_ua_hr_attendance_sheet.hr_production_calendar_company_rule',
        ]
        for ref in refs:
            rule = self.env.ref(ref)
            self.assertTrue(rule, f"Rule {ref} must exist")
            self.assertEqual(
                rule.kind, 'restriction',
                f"Rule {ref} must be a restriction")

    def test_disabled_company_is_refused_on_save(self):
        """Табель у вимкненій компанії не зберігається (record rule)."""
        active, disabled = self.env['res.company'].create([
            {'name': 'ТОВ Активна'},
            {'name': 'ТОВ Вимкнена'},
        ])
        user = self.env['res.users'].create({
            'name': 'Табельник',
            'login': 'timesheet_multicompany_user',
            'company_id': active.id,
            'company_ids': [(6, 0, (active + disabled).ids)],
            'group_ids': [(6, 0, [
                self.env.ref('l10n_ua_hr_base.group_hr_ua_officer').id,
            ])],
        })
        # Користувач має доступ до обох компаній, але увімкнена лише `active`.
        Timesheet = self.env['hr.timesheet'].with_user(user).with_context(
            allowed_company_ids=active.ids)

        with self.assertRaises(AccessError):
            Timesheet.create({
                'year': 2026,
                'month': '1',
                'company_id': disabled.id,
            })

        sheet = Timesheet.create({
            'year': 2026,
            'month': '1',
            'company_id': active.id,
        })
        self.assertEqual(sheet.company_id, active)

    def test_company_field_domain_in_views(self):
        """Випадайка компанії у формах обмежена увімкненими компаніями.

        Без домену адміністратор (`base.group_erp_manager` бачить усі
        компанії) міг обрати вимкнену компанію і впертися в AccessError
        уже під час збереження.
        """
        for ref in ('hr_timesheet_view_form',
                    'hr_production_calendar_view_form'):
            arch = self.env.ref(
                f'l10n_ua_hr_attendance_sheet.{ref}').arch
            self.assertIn("[('id', 'in', allowed_company_ids)]", arch,
                          f"{ref}: поле company_id має бути обмежене доменом")
