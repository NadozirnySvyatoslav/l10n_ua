"""Середньоденна за валютним окладом — у гривні.

Фолбек «немає розрахункових листків → беремо оклад» спрацьовує саме для
щойно прийнятого працівника, а валютний оклад найчастіше в нього й буває.
Оклад 1000 USD давав середньоденну 34 грн для відпустки і 33 грн для
лікарняного — з них і рахувалася виплата.
"""
from datetime import datetime, date

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestLeaveWageCurrency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')
        cls.env['res.currency.rate'].create({
            'name': '2026-01-01',
            'currency_id': cls.usd.id,
            'company_id': cls.company.id,
            'inverse_company_rate': 42.3532,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Валютний працівник (відпустка)',
            'company_id': cls.company.id,
        })
        version = cls.employee.current_version_id
        version.write({'wage': 1000.0})
        # Валюта окладу оголошена в модулі зарплати, якого тут може не бути:
        # без нього перевіряти нема чого, і тест чесніше пропустити.
        cls.has_salary_currency = 'salary_currency_id' in version._fields
        if cls.has_salary_currency:
            version.salary_currency_id = cls.usd

        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_LEAVE_WAGE_C_1',
            'name': 'Щорічна основна (валютний тест)',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
        })

    def setUp(self):
        super().setUp()
        if not self.has_salary_currency:
            self.skipTest('l10n_ua_hr_salary не встановлено — валюти окладу немає')

    def test_leave_average_is_converted(self):
        """Відпускна середньоденна: 1000 USD × 42.3532 / 29.3, а не 1000 / 29.3."""
        leave = self.env['hr.leave'].create({
            'name': 'Відпустка',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type.id,
            'date_from': datetime(2026, 6, 15, 8, 0, 0),
            'date_to': datetime(2026, 6, 21, 17, 0, 0),
        })

        average = leave._calculate_average_salary()

        self.assertAlmostEqual(average, round(42353.2 / 29.3, 2), places=2)
        self.assertNotAlmostEqual(average, round(1000 / 29.3, 2), places=2)

    def test_sick_leave_average_is_converted(self):
        """Лікарняна середньоденна: той самий фолбек, той самий дефект."""
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 15),
            'date_to': date(2026, 6, 20),
        })

        average = sick._calculate_average_salary()

        self.assertAlmostEqual(average, round(42353.2 / 30.44, 2), places=2)
        self.assertNotAlmostEqual(average, round(1000 / 30.44, 2), places=2)
