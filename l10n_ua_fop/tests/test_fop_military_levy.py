"""Військовий збір ФОП за групами ЄП (#330).

З 01.01.2025 ФОП 1–2 груп сплачують фіксований військовий збір — 10 %
мінімальної заробітної плати на місяць (2025 — 800 грн, 2026 — 864,70 грн),
ФОП 3 групи — 1 % доходу. До 2025 року військового збору в ЄП не було.

Покриття:
- сума за періодом для 1 і 2 груп — з довідника мінзарплати, помісячно;
- 3 група — 1 % доходу, і саме це поле йде в XML F0103309;
- військовий збір входить у «Всього до сплати»;
- F0103309 — декларація 3 групи: для 1–2 груп XML і подання відмовляють.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFopMilitaryLevy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.group_1 = cls.env.ref('l10n_ua_fop.fop_group_1')
        cls.group_2 = cls.env.ref('l10n_ua_fop.fop_group_2')
        cls.group_3 = cls.env.ref('l10n_ua_fop.fop_group_3')

    def _books(self, year, group, amounts_by_quarter):
        for quarter, amount in amounts_by_quarter.items():
            book = self.env['l10n_ua.fop.income.book'].create({
                'year': year,
                'quarter': quarter,
                'fop_group_id': group.id,
                'company_id': self.company.id,
            })
            self.env['l10n_ua.fop.income.book.line'].create({
                'book_id': book.id,
                'date': date(year, {'1': 1, '2': 4, '3': 7, '4': 10}[quarter], 15),
                'amount': amount,
                'description': f'Дохід Q{quarter}',
            })
            book.action_confirm()

    def _declaration(self, year, period, group):
        return self.env['l10n_ua.fop.declaration'].create({
            'year': year,
            'period': period,
            'fop_group_id': group.id,
            'company_id': self.company.id,
        })

    def test_group_1_fixed_levy_2026(self):
        self.assertAlmostEqual(
            self._declaration(2026, 'year', self.group_1).military_levy, 10_376.40, places=2)
        self.assertAlmostEqual(
            self._declaration(2026, 'h1', self.group_1).military_levy, 5_188.20, places=2)

    def test_group_2_fixed_levy_2025(self):
        self.assertAlmostEqual(
            self._declaration(2025, 'year', self.group_2).military_levy, 9_600.00, places=2)

    def test_group_1_levy_does_not_depend_on_income(self):
        self._books(2026, self.group_1, {'1': 1_000_000})
        decl = self._declaration(2026, 'q1', self.group_1)
        decl.action_calculate()
        self.assertAlmostEqual(decl.military_levy, 3 * 864.70, places=2)

    def test_group_3_levy_is_one_percent_of_income(self):
        self._books(2026, self.group_3, {'1': 200_000, '2': 335_000})
        decl = self._declaration(2026, 'h1', self.group_3)
        decl.action_calculate()
        self.assertAlmostEqual(decl.military_levy, 5_350.00, places=2)

    def test_no_levy_before_2025(self):
        self._books(2024, self.group_3, {'1': 100_000})
        decl = self._declaration(2024, 'q1', self.group_3)
        decl.action_calculate()
        self.assertEqual(decl.military_levy, 0.0)
        self.assertEqual(self._declaration(2024, 'year', self.group_1).military_levy, 0.0)

    def test_total_payable_includes_levy(self):
        self._books(2026, self.group_3, {'1': 100_000})
        decl = self._declaration(2026, 'q1', self.group_3)
        decl.action_calculate()
        self.assertAlmostEqual(
            decl.total_payable, decl.single_tax + decl.esv_amount + decl.military_levy, places=2)
        self.assertAlmostEqual(decl.military_levy, 1_000.00, places=2)

    def test_group_3_xml_carries_levy(self):
        self._books(2026, self.group_3, {'1': 123_456})
        decl = self._declaration(2026, 'q1', self.group_3)
        decl.action_calculate()
        decl.action_generate_xml()
        xml = decl.xml_file.content.decode('windows-1251')
        self.assertIn('<R023G3>1234.56</R023G3>', xml)
        self.assertIn('<R025G3>1234.56</R025G3>', xml)

    def test_f0103309_refused_for_groups_1_and_2(self):
        for group in (self.group_1, self.group_2):
            with self.subTest(group=group.code):
                self._books(2026, group, {'1': 50_000})
                decl = self._declaration(2026, 'q1', group)
                decl.action_calculate()
                with self.assertRaises(UserError):
                    decl.action_generate_xml()
                with self.assertRaises(UserError):
                    decl.action_kep_submit()
                self.assertFalse(decl.xml_file)
