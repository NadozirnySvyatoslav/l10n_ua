"""Multi-company record-rule isolation (issue #178).

Full isolation test on hr.psp.parameters: a user restricted to a non-UA
company must not see records belonging to another (UA) company, but must
see records of their own company. Also asserts every rule added by this
module exists and is global.
"""

from datetime import date
from odoo.exceptions import UserError
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

        # A year no seeded period uses: new companies get copies of those.
        common_vals = {
            'year': 2033,
            'date_from': date(2033, 1, 1),
            'subsistence_minimum': 3028.0,
            'min_wage': 8000.0,
            'min_hourly_wage': 48.0,
        }
        cls.psp_ua = cls.env['hr.psp.parameters'].create(
            dict(common_vals, company_id=cls.company_ua.id))
        cls.psp_other = cls.env['hr.psp.parameters'].create(
            dict(common_vals, date_from=date(2033, 2, 1),
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
            self.assertTrue(rule['global'], f"Rule {ref} must be global")


@tagged('post_install', '-at_install')
class TestPayslipCompanyScope(TransactionCase):
    """A payslip is computed on its own company's parameters, whatever
    company is active in the session switcher."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.company_a = cls.env['res.company'].create(
            {'name': 'Payslip Scope A', 'currency_id': cls.uah.id})
        cls.company_b = cls.env['res.company'].create(
            {'name': 'Payslip Scope B', 'currency_id': cls.uah.id})
        cls.env.user.company_ids |= cls.company_a | cls.company_b

        Params = cls.env['hr.psp.parameters']
        common = {
            'year': 2031,
            'date_from': date(2031, 1, 1),
            'subsistence_minimum': 4000,
            'min_hourly_wage': 60,
        }
        Params.create(dict(common, min_wage=10000, company_id=cls.company_a.id))
        Params.create(dict(common, min_wage=12000, company_id=cls.company_b.id))

        cls.employee_b = cls._create_employee(cls.company_b, date(2030, 1, 1))

    @classmethod
    def _create_employee(cls, company, start):
        employee = cls.env['hr.employee'].create({
            'name': f'Employee of {company.name}',
            'company_id': company.id,
        })
        version = cls.env['hr.version'].create({
            'employee_id': employee.id,
            'contract_date_start': start,
            'date_version': start,
            'wage': 5000,
            'salary_currency_id': cls.uah.id,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': company.id,
        })
        employee.current_version_id = version
        return employee

    def _env_with_active(self, company):
        """Environment with both companies allowed and `company` active."""
        other = (self.company_a | self.company_b) - company
        return self.env(context=dict(
            self.env.context, allowed_company_ids=[company.id, other.id]))

    def _create_payslip(self, env, employee, company, day):
        return env['hr.payslip'].create({
            'employee_id': employee.id,
            'company_id': company.id,
            'date_from': day.replace(day=1),
            'date_to': day,
        })

    def test_payslip_uses_its_company_parameters_not_the_active_one(self):
        results = []
        for active in (self.company_a, self.company_b):
            env = self._env_with_active(active)
            slip = self._create_payslip(
                env, self.employee_b, self.company_b, date(2031, 6, 30))
            slip.action_compute_sheet()
            slip.flush_recordset()
            results.append(slip.esv_base)
        # Wage 5000 is below the minimum wage, so the ESV base is floored at
        # company B's own minimum wage, not at company A's 10000.
        self.assertEqual(results, [12000, 12000])

    def test_other_company_parameters_never_used(self):
        self.env['hr.psp.parameters'].create({
            'year': 2032,
            'date_from': date(2032, 1, 1),
            'subsistence_minimum': 4000,
            'min_wage': 15000,
            'company_id': self.company_b.id,
        })
        employee_a = self._create_employee(self.company_a, date(2030, 1, 1))
        env = self._env_with_active(self.company_b)
        slip = self._create_payslip(
            env, employee_a, self.company_a, date(2032, 6, 30))
        slip.action_compute_sheet()
        slip.flush_recordset()
        # Company A's own 2031 record, not company B's newer 2032 one.
        self.assertEqual(slip.esv_base, 10000)

    def test_missing_parameters_refuse_computation(self):
        env = self._env_with_active(self.company_b)
        # No record, seeded or not, covers 2023.
        slip = self._create_payslip(
            env, self.employee_b, self.company_b, date(2023, 6, 30))
        with self.assertRaises(UserError):
            slip.action_compute_sheet()
        with self.assertRaises(UserError):
            slip.action_payslip_verify()

    def test_employee_of_another_company_rejected(self):
        env = self._env_with_active(self.company_a)
        with self.assertRaises(UserError):
            self._create_payslip(
                env, self.employee_b, self.company_a, date(2031, 6, 30))

    def test_batch_of_another_company_rejected(self):
        env = self._env_with_active(self.company_a)
        batch = env['hr.payslip.run'].create({
            'name': 'Batch A',
            'date_start': date(2031, 6, 1),
            'date_end': date(2031, 6, 30),
            'company_id': self.company_a.id,
        })
        slip = self._create_payslip(
            env, self.employee_b, self.company_b, date(2031, 6, 30))
        with self.assertRaises(UserError):
            slip.payslip_run_id = batch

    def test_company_field_limited_to_switcher_companies(self):
        arch = self.env['hr.payslip'].get_view(
            self.env.ref('l10n_ua_hr_salary.hr_payslip_view_form').id)['arch']
        self.assertIn("('id', 'in', allowed_company_ids)", arch)
