"""Tests for hr.psp.application and its integration with payslip and version."""

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPspApplication(SalaryTestCase):
    """Test suite for hr.psp.application model."""

    def setUp(self):
        super().setUp()
        # Create a second company for multi-company isolation and global validation tests
        self.company_2 = self.env['res.company'].create({
            'name': 'Друга компанія ТОВ',
            'currency_id': self.uah.id,
        })
        self.employee_2 = self.env['hr.employee'].create({
            'name': 'Петренко Олександр (Компанія 2)',
            'rnokpp': self.employee.rnokpp,
            'company_id': self.company_2.id,
        })

    def _create_payslip_with_accrual(self, amount=3000, employee=None, date_from=None, date_to=None):
        employee = employee or self.employee
        date_from = date_from or date(2025, 6, 1)
        date_to = date_to or date(2025, 6, 30)
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'date_from': date_from,
            'date_to': date_to,
        })
        self.env['hr.payslip.accrual'].create({
            'payslip_id': payslip.id,
            'accrual_type_id': self.accrual_wage.id,
            'quantity': 1,
            'rate': amount,
            'amount': amount,
        })
        payslip._compute_amounts()
        payslip._compute_psp_type()
        payslip._compute_psp()
        return payslip

    def test_psp_application_lifecycle_and_sequence(self):
        """Test sequence assignment and draft -> active -> draft transitions."""
        emp = self.env['hr.employee'].create({
            'name': 'Тестовий Працівник',
            'rnokpp': '2832345670',
            'company_id': self.company.id,
        })
        app = self.env['hr.psp.application'].create({
            'employee_id': emp.id,
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'psp_type': 'standard',
        })
        self.assertEqual(app.state, 'draft')
        self.assertTrue(app.name)
        self.assertNotEqual(app.name, 'New')

        app.action_activate()
        self.assertEqual(app.state, 'active')

        app.action_draft()
        self.assertEqual(app.state, 'draft')

    def test_psp_application_dates_validation(self):
        """date_to cannot be earlier than date_from."""
        with self.assertRaises(ValidationError):
            self.env['hr.psp.application'].create({
                'employee_id': self.employee.id,
                'company_id': self.company.id,
                'date_from': date(2025, 6, 1),
                'date_to': date(2025, 5, 31),
                'state': 'draft',
            })

    def test_psp_application_rnokpp_required_on_activate(self):
        """Activating an application requires employee to have RNOKPP."""
        emp_no_rnokpp = self.env['hr.employee'].create({
            'name': 'Іванов Іван без РНОКПП',
            'company_id': self.company.id,
        })
        app = self.env['hr.psp.application'].create({
            'employee_id': emp_no_rnokpp.id,
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
        })
        with self.assertRaises(ValidationError):
            app.action_activate()

    def test_unique_rnokpp_active_period_overlap_same_company(self):
        """Two active applications for same person (RNOKPP) cannot overlap in time."""
        # self.psp_application is active from 2024-01-15 onwards without date_to
        app_new = self.env['hr.psp.application'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'psp_type': 'standard',
        })
        with self.assertRaises(ValidationError):
            app_new.action_activate()

    def test_unique_rnokpp_active_period_overlap_different_companies(self):
        """Active applications across DIFFERENT companies for the same RNOKPP cannot overlap."""
        app_comp2 = self.env['hr.psp.application'].create({
            'employee_id': self.employee_2.id,
            'company_id': self.company_2.id,
            'date_from': date(2025, 1, 1),
            'psp_type': 'standard',
        })
        with self.assertRaises(ValidationError):
            app_comp2.action_activate()

    def test_sequential_periods_allowed(self):
        """When prior application ends, a new application starting after it is allowed."""
        # End prior application in May 2025
        self.psp_application.write({'date_to': date(2025, 5, 15)})

        # New application starting in June 2025 (after date_to month)
        app_new = self.env['hr.psp.application'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': date(2025, 6, 1),
            'psp_type': '150',
        })
        app_new.action_activate()
        self.assertEqual(app_new.state, 'active')

    def test_payslip_application_date_from_month(self):
        """PSP applies starting with the month of date_from."""
        self.psp_application.write({'state': 'draft'})  # deactivate default

        # Application filed in the middle of June 2025 (2025-06-20)
        app = self.env['hr.psp.application'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': date(2025, 6, 20),
            'psp_type': 'standard',
            'state': 'active',
        })

        # June 2025 payslip: gets PSP because filed in June
        payslip_june = self._create_payslip_with_accrual(3000, date_from=date(2025, 6, 1), date_to=date(2025, 6, 30))
        self.assertEqual(payslip_june.psp_type, 'standard')
        self.assertEqual(payslip_june.psp_amount, 1514)
        self.assertEqual(payslip_june.psp_application_id, app)

        # May 2025 payslip: NO PSP because filed in June
        payslip_may = self._create_payslip_with_accrual(3000, date_from=date(2025, 5, 1), date_to=date(2025, 5, 31))
        self.assertEqual(payslip_may.psp_type, 'none')
        self.assertEqual(payslip_may.psp_amount, 0)
        self.assertFalse(payslip_may.psp_application_id)

    def test_payslip_application_date_to_month(self):
        """In the month of date_to, PSP is NO LONGER applied (пп. 169.2.3 ПКУ)."""
        self.psp_application.write({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 7, 10),  # Withdrawn in July
            'state': 'active',
        })

        # June 2025 payslip: gets PSP (month before date_to)
        payslip_june = self._create_payslip_with_accrual(3000, date_from=date(2025, 6, 1), date_to=date(2025, 6, 30))
        self.assertEqual(payslip_june.psp_type, 'standard')
        self.assertEqual(payslip_june.psp_amount, 1514)

        # July 2025 payslip: NO PSP (withdrawn in July)
        payslip_july = self._create_payslip_with_accrual(3000, date_from=date(2025, 7, 1), date_to=date(2025, 7, 31))
        self.assertEqual(payslip_july.psp_type, 'none')
        self.assertEqual(payslip_july.psp_amount, 0)

    def test_payslip_application_fixed_psp_type(self):
        """Fixed psp_type on application determines payslip calculation."""
        self.psp_application.write({'psp_type': '150'})

        payslip = self._create_payslip_with_accrual(3000, date_from=date(2025, 6, 1), date_to=date(2025, 6, 30))
        self.assertEqual(payslip.psp_type, '150')
        self.assertEqual(payslip.psp_amount, 2271)

        self.psp_application.write({'psp_type': '200'})
        payslip._compute_psp_type()
        payslip._compute_psp()
        self.assertEqual(payslip.psp_type, '200')
        self.assertEqual(payslip.psp_amount, 3028)

    def test_hr_version_psp_application_compute_today(self):
        """hr.version.psp_application reflects active application covering today."""
        today = date.today()
        self.psp_application.write({
            'date_from': today - relativedelta(months=1),
            'date_to': False,
            'state': 'active',
        })
        self.version._compute_psp_application()
        self.assertTrue(self.version.psp_application)

        # Deactivate application
        self.psp_application.write({'state': 'draft'})
        self.version._compute_psp_application()
        self.assertFalse(self.version.psp_application)

    def test_employee_smart_button(self):
        """Test psp_application_count and action_open_psp_applications on hr.employee."""
        self.assertEqual(self.employee.psp_application_count, 1)
        action = self.employee.action_open_psp_applications()
        self.assertEqual(action['res_model'], 'hr.psp.application')
        self.assertEqual(action['domain'], [('employee_id', '=', self.employee.id)])

    def test_psp_application_report_rendering(self):
        """Test QWeb report rendering for hr.psp.application."""
        report = self.env.ref('l10n_ua_hr_salary.action_report_hr_psp_application')
        pdf_content, _ = report._render_qweb_pdf(report, self.psp_application.ids)
        self.assertTrue(pdf_content)
        self.assertTrue(len(pdf_content) > 100)
