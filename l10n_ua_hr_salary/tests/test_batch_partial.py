"""Пакет не відкочується цілком через одного працівника (#577).

Раніше листки пакета створювались і рахувались в одній транзакції: валютний
оклад без курсу на дату в одного працівника залишав без листків усю
установу. Пакет авансів, навпаки, мовчки пропускав нульовий оклад.
"""
from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPayslipRunPartial(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref('base.USD')
        cls.env['res.currency.rate'].search([
            ('currency_id', '=', cls.usd.id),
            ('company_id', 'in', (cls.company.id, False)),
        ]).unlink()
        cls.foreign = cls.env['hr.employee'].create({
            'name': 'Валютний Працівник',
            'company_id': cls.company.id,
        })
        cls.foreign.current_version_id.write({
            'wage': 1000.0,
            'salary_currency_id': cls.usd.id,
            'contract_date_start': date(2024, 1, 15),
        })

    def _run(self):
        return self.env['hr.payslip.run'].create({
            'name': 'ЗП 06/2025',
            'date_start': date(2025, 6, 1),
            'date_end': date(2025, 6, 30),
            'company_id': self.company.id,
        })

    def _messages(self, record):
        return ' '.join(record.message_ids.mapped('body'))

    def test_one_failing_employee_keeps_the_others(self):
        run = self._run()

        result = run.action_generate_payslips()

        employees = run.slip_ids.mapped('employee_id')
        self.assertIn(self.employee, employees,
                      'листок того, хто порахувався, має лишитись')
        self.assertNotIn(self.foreign, employees)
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertIn(self.foreign.name, result['params']['message'])
        self.assertIn(self.foreign.name, self._messages(run),
                      'причина має лишитись у чаттері пакета')

    def test_rerun_after_the_rate_adds_the_missing_slip_once(self):
        run = self._run()
        run.action_generate_payslips()
        count = len(run.slip_ids)
        self.env['res.currency.rate'].create({
            'name': '2025-06-01', 'currency_id': self.usd.id,
            'company_id': self.company.id, 'inverse_company_rate': 41.5,
        })

        run.action_generate_payslips()

        self.assertEqual(len(run.slip_ids), count + 1)
        self.assertEqual(
            len(run.slip_ids.filtered(lambda s: s.employee_id == self.employee)),
            1, 'повторний запуск не дублює листки')
        self.assertIn(self.foreign, run.slip_ids.mapped('employee_id'))

    def test_clean_run_reports_nothing(self):
        self.foreign.current_version_id.salary_currency_id = self.uah
        run = self._run()
        before = len(run.message_ids)

        self.assertIs(run.action_generate_payslips(), True)
        self.assertEqual(len(run.message_ids), before)


@tagged('post_install', '-at_install')
class TestAdvanceRunReportsSkipped(SalaryTestCase):

    def test_zero_wage_is_reported(self):
        zero = self.env['hr.employee'].create({
            'name': 'Нульовий Оклад',
            'company_id': self.company.id,
        })
        zero.current_version_id.write({
            'wage': 0.0, 'contract_date_start': date(2024, 1, 15)})
        self.company.wage_from_staffing = 'none'
        run = self.env['hr.salary.advance.run'].create({
            'name': 'Аванс 06/2025',
            'date': date(2025, 6, 15),
            'company_id': self.company.id,
        })

        result = run.action_generate_advances()

        self.assertNotIn(zero, run.advance_ids.mapped('employee_id'))
        self.assertIn(self.employee, run.advance_ids.mapped('employee_id'))
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertIn(zero.name, result['params']['message'])
        self.assertIn(zero.name, ' '.join(run.message_ids.mapped('body')))
