"""#417 — погодинна оплата за проведення навчальних занять (ПКМУ № 1078)."""

from datetime import date

from odoo.exceptions import ValidationError
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
