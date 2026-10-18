"""Оклад у валюті: один хелпер для всіх, хто раніше читав `wage` як гривні.

Мовчазна помилка коштує дорого: оклад 1000 USD, прочитаний як гривні, дає
аванс 500 грн і середньоденну для відпустки 34 грн. Тому перевіряється не
лише «правильне число», а й кожен спосіб не отримати його непомітно.
"""
from datetime import date
from unittest import SkipTest

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestWageInCompanyCurrency(TestHrUaBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Валюту окладу додає l10n_ua_hr_salary, від якого цей модуль не
        # залежить: без нього перевіряти нічого.
        if 'salary_currency_id' not in cls.env['hr.version']._fields:
            raise SkipTest('salary_currency_id comes with l10n_ua_hr_salary')
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')
        cls.company.currency_id = cls.uah
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Валютний працівник',
            'company_id': cls.company.id,
        })
        cls.version = cls.employee.current_version_id
        cls.version.write({'wage': 1000.0, 'company_id': cls.company.id})
        # Курс міняється в часі — на цьому тримається половина тестів нижче.
        cls.env['res.currency.rate'].create([
            {'name': '2026-01-01', 'currency_id': cls.usd.id,
             'company_id': cls.company.id, 'inverse_company_rate': 42.3532},
            {'name': '2026-06-01', 'currency_id': cls.usd.id,
             'company_id': cls.company.id, 'inverse_company_rate': 44.2680},
        ])

    def _in_currency(self, currency):
        self.version.salary_currency_id = currency
        return self.version

    def test_company_currency_wage_is_returned_as_is(self):
        """Гривневий оклад ніхто не чіпає — і жодного запиту курсу."""
        version = self._in_currency(self.uah)

        self.assertEqual(
            version._l10n_ua_wage_in_company_currency(date(2026, 6, 15)), 1000.0)

    def test_wage_without_currency_field_value(self):
        """Порожня валюта окладу означає валюту компанії, а не помилку."""
        self.version.salary_currency_id = False

        self.assertEqual(
            self.version._l10n_ua_wage_in_company_currency(date(2026, 6, 15)), 1000.0)

    def test_foreign_wage_uses_the_rate_of_that_date(self):
        """Курс береться на потрібну дату, а не останній наявний."""
        version = self._in_currency(self.usd)

        self.assertAlmostEqual(
            version._l10n_ua_wage_in_company_currency(date(2026, 3, 15)),
            42353.2, places=1)
        self.assertAlmostEqual(
            version._l10n_ua_wage_in_company_currency(date(2026, 6, 15)),
            44268.0, places=1)

    def test_rate_is_not_rounded_to_kopiykas(self):
        """Курс не стискається до копійки: 44.2680, а не 44.27.

        `_convert` заокруглює результат за валютою призначення, тож перерахунок
        одиниці дав би 44.27 і зайві дві гривні на кожній тисячі окладу.
        """
        version = self._in_currency(self.usd)

        self.assertAlmostEqual(
            version._l10n_ua_wage_in_company_currency(date(2026, 6, 15)),
            44268.0, places=2)

    def test_missing_rate_is_refused_not_guessed(self):
        """Без курсу на дату — відмова, бо мовчазна одиниця дає оклад у 40 разів менший."""
        version = self._in_currency(self.usd)

        with self.assertRaises(UserError):
            version._l10n_ua_wage_in_company_currency(date(2025, 12, 31))

    def test_zero_wage_needs_no_rate(self):
        """Нульовий оклад не потребує курсу — множити нема чого."""
        version = self._in_currency(self.usd)
        version.wage = 0.0

        self.assertEqual(
            version._l10n_ua_wage_in_company_currency(date(2025, 12, 31)), 0.0)
