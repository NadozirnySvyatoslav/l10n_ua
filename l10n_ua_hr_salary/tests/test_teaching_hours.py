"""#417 — погодинна оплата за проведення навчальних занять (ПКМУ № 1078)."""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestTeachingHours(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env['hr.teaching.hours.entry']
        # Бакалаври/магістри: професор — 2,2 %, без ступеня — 1,1 % базової величини.
        cls.professor = cls.env.ref('l10n_ua_hr_base.pay_scheme_1078_hourly_05')
        cls.no_degree = cls.env.ref('l10n_ua_hr_base.pay_scheme_1078_hourly_08')

    def _entry(self, **vals):
        base = {'name': 'Лекції', 'employee_id': self.employee.id,
                'date': date(2027, 2, 10), 'hours': 10, 'company_id': self.company.id}
        base.update(vals)
        return self.Entry.create(base)

    def test_scheme_rate_rounded_to_hryvnia(self):
        # 28 885 × 2,2 % = 635,47 → 635; 28 885 × 1,1 % = 317,735 → 318.
        self.assertEqual(self._entry(pay_scheme_line_id=self.professor.id).hourly_rate, 635)
        entry = self._entry(pay_scheme_line_id=self.no_degree.id)
        self.assertEqual(entry.hourly_rate, 318)
        self.assertEqual(entry.amount, 3180)

    def test_academician_raise(self):
        # 635 × 1,25 = 793,75 → 794.
        entry = self._entry(pay_scheme_line_id=self.professor.id, academician=True)
        self.assertEqual(entry.hourly_rate, 794)

    def test_scheme_refused_before_2027(self):
        with self.assertRaises(ValidationError):
            self._entry(pay_scheme_line_id=self.professor.id, date=date(2026, 12, 15))

    def test_manual_rate_without_scheme(self):
        entry = self._entry(date=date(2025, 6, 5), hourly_rate=150.0, hours=4)
        self.assertEqual(entry.amount, 600.0)

    def test_payslip_accrual_on_top_of_salary(self):
        self._entry(date=date(2025, 6, 5), hourly_rate=150.0, hours=4)
        self._entry(date=date(2025, 6, 25), hourly_rate=150.0, hours=6)
        self._entry(date=date(2025, 7, 1), hourly_rate=150.0, hours=8)  # інший місяць
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'version_id': self.version.id,
            'date_from': date(2025, 6, 1), 'date_to': date(2025, 6, 30),
        })
        slip.write({'scheduled_hours': 160.0, 'scheduled_days': 20, 'worked_days': 20,
                    'worked_hours': 160.0})
        slip._generate_accruals()
        teach = slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == 'TEACH_HOURLY')
        self.assertEqual(len(teach), 1)
        self.assertAlmostEqual(teach.amount, 1500.0)
        self.assertAlmostEqual(teach.quantity, 10.0)
        self.assertAlmostEqual(teach.rate, 150.0)
        self.assertTrue(slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == 'SALARY'))


@tagged('post_install', '-at_install')
class TestTeachingHours1078(SalaryTestCase):
    """Критерії К6–К10 і Р1 постановки #417 (числа — з постановки BA)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env['hr.teaching.hours.entry']
        if not cls.env['hr.psp.parameters'].search([
                ('year', '=', 2027), ('company_id', '=', cls.company.id)], limit=1):
            # Тестові параметри 2027: від них тут залежать лише ПСП і межі
            # бази ЄСВ, які сума листка К10 не зачіпає.
            cls.env['hr.psp.parameters'].create({
                'year': 2027, 'date_from': date(2027, 1, 1),
                'subsistence_minimum': 3328, 'min_wage': 8647,
                'company_id': cls.company.id,
            })

    def _line(self, n):
        return self.env.ref('l10n_ua_hr_base.pay_scheme_1078_hourly_%02d' % n)

    def _entry(self, **vals):
        base = {'name': 'Лекції', 'employee_id': self.employee.id,
                'date': date(2027, 2, 10), 'hours': 1, 'company_id': self.company.id}
        base.update(vals)
        return self.Entry.create(base)

    def _slip(self, date_from, date_to):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'version_id': self.version.id,
            'date_from': date_from, 'date_to': date_to,
        })
        slip.write({'scheduled_hours': 160.0, 'scheduled_days': 20, 'worked_days': 20,
                    'worked_hours': 160.0})
        return slip

    def test_k6_all_hourly_rates(self):
        # 28 885 × % на 10.02.2027, до гривні (менше 0,5 відкидається).
        expected = {1: 347, 2: 289, 3: 231, 4: 202,     # 1,2 / 1 / 0,8 / 0,7 %
                    5: 635, 6: 520, 7: 404, 8: 318,     # 2,2 / 1,8 / 1,4 / 1,1 %
                    9: 751, 10: 607, 11: 491, 12: 404}  # 2,6 / 2,1 / 1,7 / 1,4 %
        for n, rate in expected.items():
            with self.subTest(line=n):
                self.assertEqual(self._entry(pay_scheme_line_id=self._line(n).id).hourly_rate,
                                 rate)

    def test_k7_academician_rounds_from_rounded_rate(self):
        # Прямий підрахунок 28 885 × % × 1,25 дає на 1 грн менше в перших трьох.
        cases = {1: (434, 433), 8: (398, 397), 10: (759, 758), 5: (794, 794), 2: (361, 361)}
        for n, (rate, direct) in cases.items():
            with self.subTest(line=n):
                line = self._line(n)
                entry = self._entry(pay_scheme_line_id=line.id, academician=True)
                self.assertEqual(entry.hourly_rate, rate)
                self.assertEqual(round(28885 * line.coefficient * 1.25), direct)

    def test_k8_scheme_refused_manual_rate_allowed_in_2026(self):
        with self.assertRaises(ValidationError):
            self._entry(pay_scheme_line_id=self._line(5).id, date=date(2026, 12, 15))
        entry = self._entry(date=date(2026, 12, 15), hourly_rate=150.0, hours=4)
        self.assertEqual(entry.amount, 600.0)

    def test_k10_february_2027_payslip(self):
        self.version.wage = 15020
        self._entry(pay_scheme_line_id=self._line(5).id, hours=10)                 # 635
        self._entry(pay_scheme_line_id=self._line(8).id, hours=6,
                    date=date(2027, 2, 17))                                          # 318
        slip = self._slip(date(2027, 2, 1), date(2027, 2, 28))
        slip._generate_accruals()
        teach = slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == 'TEACH_HOURLY')
        self.assertEqual(len(teach), 1)
        self.assertAlmostEqual(teach.quantity, 16)
        self.assertAlmostEqual(teach.amount, 8258)
        self.assertAlmostEqual(teach.rate, 516.125)
        salary = slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == 'SALARY')
        self.assertAlmostEqual(sum(salary.mapped('amount')), 15020)
        # Утримання — з усієї суми 23 278.
        self.assertAlmostEqual(slip.gross_salary, 23278)
        self.assertAlmostEqual(slip.pdfo_base, 23278)
        self.assertAlmostEqual(slip.pdfo_amount, 4190.04)       # 18 %
        self.assertAlmostEqual(slip.military_tax_base, 23278)
        self.assertAlmostEqual(slip.military_tax_amount, 1163.9)  # 5 %
        self.assertAlmostEqual(slip.esv_base, 23278)
        self.assertAlmostEqual(slip.esv_amount, 5121.16)        # 22 %

    def test_k9_entries_locked_in_done_payslip(self):
        entry = self._entry(hourly_rate=150.0, hours=4)
        slip = self._slip(date(2027, 2, 1), date(2027, 2, 28))
        slip._generate_accruals()
        slip.action_payslip_done()
        with self.assertRaisesRegex(UserError, 'скасуйте листок'):
            entry.write({'hours': 5})
        with self.assertRaisesRegex(UserError, 'скасуйте листок'):
            entry.unlink()
        with self.assertRaisesRegex(UserError, 'скасуйте листок'):
            self._entry(hourly_rate=150.0, hours=2, date=date(2027, 2, 20))
        march = self._entry(hourly_rate=150.0, hours=2, date=date(2027, 3, 3))
        with self.assertRaisesRegex(UserError, 'скасуйте листок'):
            march.write({'date': date(2027, 2, 27)})  # перенесення в закритий місяць
        slip.action_payslip_draft()
        entry.write({'hours': 5})
        self.assertEqual(entry.amount, 750.0)
        entry.unlink()

    def test_k9_cancelled_payslip_does_not_lock(self):
        entry = self._entry(hourly_rate=150.0, hours=4)
        slip = self._slip(date(2027, 2, 1), date(2027, 2, 28))
        slip.action_payslip_cancel()
        entry.write({'hours': 6})
        self.assertEqual(entry.amount, 900.0)

    def test_r1_not_in_vacation_average(self):
        # Ставки включають оплату за дні відпустки (примітка 4) → не в середню;
        # податки і база лікарняних — як для зарплати.
        acc = self.env.ref('l10n_ua_hr_salary.accrual_type_teaching_hourly')
        self.assertFalse(acc.is_basic_salary)
        self.assertTrue(acc.is_taxable_pdfo)
        self.assertTrue(acc.is_military_tax)
        self.assertTrue(acc.is_esv_base)
