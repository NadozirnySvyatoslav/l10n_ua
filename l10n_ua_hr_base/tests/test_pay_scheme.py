"""Salaries in coefficients of a base value (CMU Resolution No 1078, #323).

From 1 September 2026 a teacher of a state or communal institution is paid
the base value of 28 885 UAH times the coefficient of the position, instead of
a grade of the Unified Tariff Grid. The periods before that date keep the
grid salary.
"""

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPayScheme(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.company = cls.env['res.company'].create({
            'name': 'Ліцей №1', 'currency_id': cls.uah.id})
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.teacher_top = cls.env.ref('l10n_ua_hr_base.pay_scheme_1078_ped_39')
        cls.teacher_none = cls.env.ref('l10n_ua_hr_base.pay_scheme_1078_ped_36')
        cls.department = cls.env['hr.department'].create({
            'name': 'Педагогічний колектив', 'company_id': cls.company.id})
        cls.job = cls.env['hr.job'].create({
            'name': 'Вчитель', 'company_id': cls.company.id})

    def test_data_follows_the_act(self):
        base = self.env.ref('l10n_ua_hr_base.pay_base_value_2026_09')
        self.assertEqual(base.date_from, date(2026, 9, 1))
        self.assertEqual(base.amount, 28885.0)
        self.assertEqual(self.teacher_top.name, 'спеціаліст вищої категорії')
        self.assertIn('Вчителі всіх спеціальностей', self.teacher_top.group_name)
        self.assertEqual(self.teacher_top.coefficient, 0.52)
        self.assertEqual(self.teacher_none.coefficient, 0.48)
        rector = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_he_01')
        self.assertEqual(rector.coefficient, 0.99)
        pedagogical = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_pedagogical')
        self.assertEqual(len(pedagogical.line_ids), 55)
        self.assertEqual(len(rector.scheme_id.line_ids), 20)
        hourly = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_hourly')
        self.assertEqual(hourly.date_from, date(2027, 1, 1),
                         'hourly rates apply from 1 January 2027 (p. 2.4)')
        self.assertEqual(len(hourly.line_ids), 12)

    def test_amount_is_rounded_half_up_to_a_hryvnia(self):
        # 28 885 × 0.52 = 15 020.20 → 15 020; × 0.49 = 14 153.65 → 14 154;
        # × 0.63 = 18 197.55 → 18 198 (note 1: 0.5 and above goes up).
        self.assertEqual(self.teacher_top._amount_on(date(2026, 9, 1)), 15020.0)
        cat2 = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_ped_37')
        self.assertEqual(cat2._amount_on(date(2026, 9, 1)), 14154.0)
        head = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_ped_01')
        self.assertEqual(head._amount_on(date(2026, 10, 1)), 18198.0)
        hourly = self.env.ref('l10n_ua_hr_base.pay_scheme_1078_hourly_08')
        self.assertEqual(hourly._amount_on(date(2027, 1, 1)), 318.0)  # 1.1 %

    def test_base_value_is_read_for_the_date(self):
        self.env['hr.pay.base.value'].create({
            'date_from': date(2027, 1, 1), 'amount': 30000.0})
        self.assertEqual(self.teacher_top._amount_on(date(2026, 12, 31)), 15020.0)
        self.assertEqual(self.teacher_top._amount_on(date(2027, 1, 1)), 15600.0)

    def test_scheme_refused_before_it_applies(self):
        with self.assertRaises(ValidationError):
            self.teacher_top._amount_on(date(2026, 8, 31))

    def _staffing(self, date_from, **vals):
        return self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'date_from': date_from,
            'state': 'approved',
            **vals,
        })

    def test_staffing_line_keeps_the_grid_before_september(self):
        """The case of the issue: one position, two periods, two rules."""
        self._staffing(date(2026, 1, 1), salary=9500.0)
        september = self._staffing(
            date(2026, 9, 1), pay_scheme_line_id=self.teacher_top.id)
        self.assertEqual(september.salary, 15020.0)
        self.assertEqual(september.pay_scheme_salary, 15020.0)

        employee = self.env['hr.employee'].create({
            'name': 'Коваленко Ірина', 'company_id': self.company.id})
        version = employee.version_id
        version.write({
            'department_id': self.department.id, 'job_id': self.job.id,
            'wage': 0.0, 'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1)})
        self.assertEqual(version._l10n_ua_effective_wage(date(2026, 8, 31)), 9500.0)
        self.assertEqual(version._l10n_ua_effective_wage(date(2026, 9, 1)), 15020.0)

    def test_staffing_line_with_scheme_before_it_applies_is_refused(self):
        with self.assertRaises(ValidationError):
            self._staffing(date(2026, 8, 1), salary=9500.0,
                           pay_scheme_line_id=self.teacher_top.id)
        line = self._staffing(date(2026, 8, 1), salary=9500.0)
        with self.assertRaises(ValidationError):
            line.pay_scheme_line_id = self.teacher_top

    def test_staffing_salary_stays_editable(self):
        # P. 7 and 8 let the institution or its founder set the concrete
        # salary; the scheme fills it, it does not lock it.
        line = self._staffing(date(2026, 9, 1), salary=16000.0,
                              pay_scheme_line_id=self.teacher_top.id)
        self.assertEqual(line.salary, 16000.0)
        self.assertEqual(line.pay_scheme_salary, 15020.0)

    def test_version_from_september_takes_the_scheme_wage(self):
        employee = self.env['hr.employee'].create({
            'name': 'Шевченко Олег', 'company_id': self.company.id})
        old = employee.version_id
        old.write({'wage': 9500.0, 'date_version': date(2026, 1, 1),
                   'contract_date_start': date(2026, 1, 1)})
        new = employee.create_version({
            'date_version': date(2026, 9, 1),
            'pay_scheme_line_id': self.teacher_none.id,
        })
        # 28 885 × 0.48 = 13 864.80 → 13 865.
        self.assertEqual(new.wage, 13865.0)
        self.assertEqual(old.wage, 9500.0, 'the period before keeps its wage')
        self.assertFalse(old.pay_scheme_line_id)
        # Category changes: the wage follows the new position.
        new.pay_scheme_line_id = self.teacher_top
        self.assertEqual(new.wage, 15020.0)
        with self.assertRaises(ValidationError):
            old.pay_scheme_line_id = self.teacher_top

    def test_employee_form_fills_the_wage(self):
        employee = self.env['hr.employee'].create({
            'name': 'Бондар Марія', 'company_id': self.company.id})
        employee.version_id.date_version = date(2026, 9, 1)
        with Form(employee) as form:
            form.pay_scheme_line_id = self.teacher_top
            self.assertEqual(form.pay_scheme_salary, 15020.0)
            self.assertEqual(form.wage, 15020.0)
        self.assertEqual(employee.version_id.wage, 15020.0)
