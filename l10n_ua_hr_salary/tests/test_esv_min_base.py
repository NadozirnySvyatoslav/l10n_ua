"""#573 — мінімальна база ЄСВ (абз. 2–3 ч. 5 ст. 8 Закону № 2464-VI), порт з 19.0.

Дотяжка бази до мінімальної зарплати — лише за основним місцем роботи
(і внутрішнім сумісництвом), за повний місяць, і не для ставки 8,41 %.
Без параметрів за період — помилка, а не вигадані 8000 / 120000.

Червень 2025: 1-ше — неділя, мінімальна зарплата 8000 грн.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestEsvMinBase(SalaryTestCase):

    def _create_payslip_with_accrual(self, amount, **kwargs):
        vals = {
            'employee_id': self.employee.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        payslip = self.env['hr.payslip'].create(vals)
        self.env['hr.payslip.accrual'].create({
            'payslip_id': payslip.id,
            'accrual_type_id': self.accrual_wage.id,
            'quantity': 1,
            'rate': amount,
            'amount': amount,
        })
        return payslip

    def _new_employee(self, start, end=False, employment='primary'):
        employee = self.env['hr.employee'].create({
            'name': 'Коваленко Ірина Петрівна',
            'company_id': self.company.id,
        })
        version = self.env['hr.version'].create({
            'employee_id': employee.id,
            'contract_date_start': start,
            'contract_date_end': end,
            'date_version': start,
            'wage': 20000,
            'contract_type_ua': 'permanent',
            'employment_type_ua': employment,
            'company_id': self.company.id,
        })
        employee.write({'current_version_id': version.id})
        return employee

    # --- основне місце / сумісництво -------------------------------------

    def test_primary_full_month_below_minimum_is_topped_up(self):
        """Сценарій QA 2: основне місце, 4000, повний місяць → база 8000, ЄСВ 1760."""
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 8000)
        self.assertAlmostEqual(payslip.esv_amount, 1760.0, places=2)

    def test_internal_secondary_job_is_topped_up(self):
        self.version.employment_type_ua = 'internal'
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 8000)

    def test_external_secondary_job_charged_on_actual(self):
        """Сценарій QA 1: зовнішній сумісник, 4000 → база 4000, ЄСВ 880."""
        self.version.employment_type_ua = 'external'
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 4000)
        self.assertAlmostEqual(payslip.esv_amount, 880.0, places=2)

    def test_ceiling_still_applies(self):
        payslip = self._create_payslip_with_accrual(200000)
        self.assertEqual(payslip.esv_base, self.psp_params.max_esv_base)

    # --- неповний місяць -------------------------------------------------

    def test_hired_mid_month_charged_on_actual(self):
        """Сценарій QA 3: прийнятий 15-го — база = фактичне нарахування."""
        self.employee = self._new_employee(date(2025, 6, 15))
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 4000)

    def test_dismissed_mid_month_charged_on_actual(self):
        self.employee = self._new_employee(date(2024, 1, 1), end=date(2025, 6, 13))
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 4000)

    def test_hired_on_first_working_day_is_topped_up(self):
        """1 червня — неділя: прийнятий у понеділок 2-го відпрацював усі
        робочі дні місяця — дотяжка до мінімуму."""
        self.employee = self._new_employee(date(2025, 6, 2))
        payslip = self._create_payslip_with_accrual(4000)
        self.assertEqual(payslip.esv_base, 8000)

    # --- інвалідність ----------------------------------------------------

    def test_disabled_employee_charged_841_on_actual(self):
        self.employee.benefit_ids = [
            (4, self.env.ref('l10n_ua_hr_base.benefit_disability_2').id)]
        payslip = self._create_payslip_with_accrual(4000)
        self.assertTrue(payslip.is_disability)
        self.assertEqual(payslip.esv_base, 4000)
        self.assertAlmostEqual(payslip.esv_amount, 336.4, places=2)

    def test_disability_group_on_card_counts(self):
        self.employee.disability_group = '3'
        payslip = self._create_payslip_with_accrual(4000)
        self.assertTrue(payslip.is_disability)
        self.assertEqual(payslip.esv_base, 4000)

    def test_parent_of_disabled_child_is_not_disabled(self):
        """DISABLED_CHILD (укр. назва містить «інвалід») ставку не знижує."""
        benefit = self.env.ref('l10n_ua_hr_base.benefit_disabled_child')
        benefit.name = 'Батько дитини з інвалідністю'
        self.employee.benefit_ids = [(4, benefit.id)]
        payslip = self._create_payslip_with_accrual(4000)
        self.assertFalse(payslip.is_disability)
        self.assertEqual(payslip.esv_base, 8000)

    # --- без параметрів --------------------------------------------------

    def test_no_parameters_no_hardcoded_floor(self):
        """Сценарій QA 5: параметрів за 2020 немає — ні 8000, ні 120000."""
        payslip = self._create_payslip_with_accrual(
            4000, date_from=date(2020, 6, 1), date_to=date(2020, 6, 30))
        self.assertFalse(self.env['hr.psp.parameters'].get_parameters(date(2020, 6, 30)))
        self.assertEqual(payslip.esv_base, 4000)
        with self.assertRaises(UserError):
            payslip.action_compute_sheet()
