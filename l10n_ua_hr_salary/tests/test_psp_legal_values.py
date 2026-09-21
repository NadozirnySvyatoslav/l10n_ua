"""Параметри ПСП, мінзарплата і прожитковий мінімум — за законом (#329).

Звірено з законами про Держбюджет (№ 3460-IX на 2024, № 4059-IX на 2025,
№ 4695-IX на 2026) і п. 169.4.1 ПКУ.

Покриття:
- прожитковий мінімум для працездатних: 3028 грн з 01.01.2024 і весь 2025 рік,
  3328 грн з 01.01.2026;
- мінімальна зарплата: 7100 → 8000 з 01.04.2024, 8000 весь 2025 рік (підвищення
  з 01.04.2025 не було), 8647 з 01.01.2026;
- граничний дохід для ПСП = ПМ × 1,4, округлений до найближчих 10 грн:
  4240 грн у 2025, 4660 грн у 2026 (а не ПМ × 1,4 × 10);
- ПСП 100 % = 50 % ПМ: 1514 грн у 2025, 1664 грн у 2026.
"""

from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPspLegalValues(TransactionCase):

    def _params(self, on_date):
        params = self.env['hr.psp.parameters'].get_parameters(on_date)
        self.assertTrue(params, f'Немає параметрів ПСП на {on_date}')
        return params

    def test_subsistence_minimum_and_min_wage(self):
        cases = [
            (date(2024, 2, 1), 3028, 7100),
            (date(2024, 5, 1), 3028, 8000),
            (date(2025, 2, 1), 3028, 8000),
            (date(2025, 6, 1), 3028, 8000),
            (date(2025, 12, 31), 3028, 8000),
            (date(2026, 9, 1), 3328, 8647),
        ]
        for on_date, subsistence, min_wage in cases:
            with self.subTest(on_date=on_date):
                params = self._params(on_date)
                self.assertEqual(params.subsistence_minimum, subsistence)
                self.assertEqual(params.min_wage, min_wage)

    def test_psp_income_limit_is_rounded_to_ten(self):
        self.assertEqual(self._params(date(2025, 6, 1)).income_limit, 4240)
        self.assertEqual(self._params(date(2026, 6, 1)).income_limit, 4660)

    def test_psp_amounts(self):
        params = self._params(date(2026, 6, 1))
        self.assertEqual(params.psp_standard, 1664)
        self.assertEqual(params.psp_150, 2496)
        self.assertEqual(params.psp_200, 3328)

    def test_max_esv_base_2026(self):
        self.assertEqual(self._params(date(2026, 6, 1)).max_esv_base, 15 * 8647)

    def test_no_fictitious_april_2025_increase(self):
        self.assertEqual(self._params(date(2025, 6, 1)).date_from, date(2025, 1, 1))
