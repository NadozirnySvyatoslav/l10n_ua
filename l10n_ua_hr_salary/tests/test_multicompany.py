"""Multi-company record-rule isolation (issue #178).

Full isolation test on hr.psp.parameters: a user restricted to a non-UA
company must not see records belonging to another (UA) company, but must
see records of their own company. Also asserts every rule added by this
module exists and is global.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalaryMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_ua = cls.env['res.company'].create({'name': 'UA Co'})
        cls.company_other = cls.env['res.company'].create({'name': 'Other Co'})

        # User restricted to the non-UA company with HR access.
        cls.user_other = cls.env['res.users'].create({
            'name': 'Restricted HR User',
            'login': 'restricted_hr_user_178',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(4, cls.env.ref('l10n_ua_hr_base.group_hr_ua_user').id)],
        })

        common_vals = {
            'year': 2026,
            'date_from': date(2026, 1, 1),
            'subsistence_minimum': 3028.0,
            'min_wage': 8000.0,
            'min_hourly_wage': 48.0,
        }
        cls.psp_ua = cls.env['hr.psp.parameters'].create(
            dict(common_vals, company_id=cls.company_ua.id))
        cls.psp_other = cls.env['hr.psp.parameters'].create(
            dict(common_vals, date_from=date(2026, 2, 1),
                 company_id=cls.company_other.id))

    def test_restricted_user_cannot_see_other_company_record(self):
        visible = self.env['hr.psp.parameters'].with_user(
            self.user_other).search([])
        self.assertIn(self.psp_other, visible,
                      "User must see their own company's record")
        self.assertNotIn(self.psp_ua, visible,
                         "User must NOT see another company's record")

    def test_rules_exist_and_are_global(self):
        refs = [
            'l10n_ua_hr_salary.hr_execution_document_company_rule',
            'l10n_ua_hr_salary.hr_payslip_company_rule',
            'l10n_ua_hr_salary.hr_payslip_run_company_rule',
            'l10n_ua_hr_salary.hr_salary_advance_company_rule',
            'l10n_ua_hr_salary.hr_salary_advance_run_company_rule',
            'l10n_ua_hr_salary.hr_psp_parameters_company_rule',
        ]
        for ref in refs:
            rule = self.env.ref(ref)
            self.assertTrue(rule, f"Rule {ref} must exist")
            self.assertEqual(
                rule.kind, 'restriction',
                f"Rule {ref} must be a restriction")
