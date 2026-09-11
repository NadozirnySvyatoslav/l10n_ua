"""Tests for salary advance feature — PR #24 review point 5.

Covers:
- Tax computation: standard (PDFO 18%, military 5%)
- Tax computation: Дія.Сіті (PDFO 5%, military 0%)
- Batch generation idempotency
- action_payslip_done → advance.state = 'paid'
- action_payslip_cancel → advance reverts to confirmed, payslip_id cleared
- Reparse safety: no duplicate ADVANCE deductions
"""

from datetime import date
from odoo.tests import tagged
from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestSalaryAdvance(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.advance_type = cls.env['hr.deduction.type'].search(
            [('code', '=', 'ADVANCE')], limit=1
        )
        if not cls.advance_type:
            cls.advance_type = cls.env['hr.deduction.type'].create({
                'name': 'Аванс',
                'code': 'ADVANCE',
                'category': 'other',
                'calculation_method': 'fixed',
            })

        # Separate employee with gig contract for Diia.City tests
        cls.employee_gig = cls.env['hr.employee'].create({
            'name': 'Коваль Іван Петрович',
            'company_id': cls.company.id,
        })
        cls.version_gig = cls.env['hr.version'].create({
            'employee_id': cls.employee_gig.id,
            'contract_date_start': date(2025, 1, 1),
            'date_version': date(2025, 1, 1),
            'wage': 25000,
            'contract_type_ua': 'gig',
            'employment_type_ua': 'primary',
            'company_id': cls.company.id,
        })
        cls.employee_gig.write({'current_version_id': cls.version_gig.id})

    def _make_advance(self, employee=None, **kw):
        vals = {
            'employee_id': (employee or self.employee).id,
            'date': date(2025, 6, 15),
            'wage_percent': 50.0,
            'company_id': self.company.id,
        }
        vals.update(kw)
        return self.env['hr.salary.advance'].create(vals)

    def _make_payslip(self, employee=None, gross=25000):
        employee = employee or self.employee
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'company_id': self.company.id,
        })
        self.env['hr.payslip.accrual'].create({
            'payslip_id': payslip.id,
            'accrual_type_id': self.accrual_wage.id,
            'quantity': 1,
            'rate': gross,
            'amount': gross,
        })
        return payslip

    # ── Tax computation ──────────────────────────────────────────────────────

    def test_gross_amount_computed_from_wage_percent(self):
        """gross_amount = version.wage × wage_percent / 100."""
        # version.wage = 25000, 50% → 12500
        advance = self._make_advance(wage_percent=50.0)
        self.assertEqual(advance.gross_amount, 12500.0)

    def test_taxes_standard_rates(self):
        """Standard: PDFO 18%, military 5%, net = gross - pdfo - military."""
        advance = self._make_advance(wage_percent=50.0)
        # gross = 12500
        self.assertAlmostEqual(advance.pdfo_amount, 2250.0, places=2)     # 18%
        self.assertAlmostEqual(advance.military_amount, 625.0, places=2)  # 5%
        self.assertAlmostEqual(advance.amount, 9625.0, places=2)          # net

    def test_taxes_diia_city(self):
        """Дія.Сіті: PDFO 5%, military 0%."""
        advance = self._make_advance(employee=self.employee_gig, wage_percent=50.0)
        # gross = 12500
        self.assertAlmostEqual(advance.pdfo_amount, 625.0, places=2)     # 5%
        self.assertAlmostEqual(advance.military_amount, 0.0, places=2)   # 0%
        self.assertAlmostEqual(advance.amount, 11875.0, places=2)

    def test_net_amount_less_than_gross(self):
        """Net amount must always be less than gross for standard employee."""
        advance = self._make_advance()
        self.assertGreater(advance.gross_amount, 0)
        self.assertLess(advance.amount, advance.gross_amount)

    # ── Batch generation idempotency ─────────────────────────────────────────

    def test_generate_advances_idempotent(self):
        """Calling Generate Advances twice creates only one advance per employee."""
        run = self.env['hr.salary.advance.run'].create({
            'name': 'Тест Аванс Червень 2025',
            'date': date(2025, 6, 15),
            'wage_percent': 50.0,
            'company_id': self.company.id,
        })
        run.action_generate_advances()
        run.action_generate_advances()

        employee_advances = run.advance_ids.filtered(
            lambda a: a.employee_id == self.employee
        )
        self.assertEqual(len(employee_advances), 1)

    def test_generate_advances_recalculates_after_percent_change(self):
        """Changing wage_percent and regenerating updates advance amounts."""
        run = self.env['hr.salary.advance.run'].create({
            'name': 'Тест Аванс Червень 2025 v2',
            'date': date(2025, 6, 15),
            'wage_percent': 50.0,
            'company_id': self.company.id,
        })
        run.action_generate_advances()
        gross_50 = run.advance_ids.filtered(
            lambda a: a.employee_id == self.employee
        ).gross_amount

        run.write({'wage_percent': 75.0})
        run.action_generate_advances()

        advance_after = run.advance_ids.filtered(
            lambda a: a.employee_id == self.employee
        )
        self.assertEqual(len(advance_after), 1)
        self.assertGreater(advance_after.gross_amount, gross_50)

    # ── Payslip state transitions ─────────────────────────────────────────────

    def test_payslip_done_sets_advance_paid(self):
        """action_payslip_done transitions linked advances to 'paid'."""
        advance = self._make_advance()
        advance.action_confirm()

        payslip = self._make_payslip()
        payslip._generate_deductions()
        self.assertEqual(advance.payslip_id, payslip)

        payslip.action_payslip_verify()
        payslip.action_payslip_done()
        advance.invalidate_recordset()
        self.assertEqual(advance.state, 'paid')

    def test_payslip_cancel_reverts_advance_to_confirmed(self):
        """action_payslip_cancel reverts advances to confirmed and clears payslip_id."""
        advance = self._make_advance()
        advance.action_confirm()

        payslip = self._make_payslip()
        payslip._generate_deductions()
        payslip.action_payslip_verify()
        payslip.action_payslip_done()
        payslip.action_payslip_cancel()

        advance.invalidate_recordset()
        self.assertEqual(advance.state, 'confirmed')
        self.assertFalse(advance.payslip_id)

    # ── Reparse safety ────────────────────────────────────────────────────────

    def test_reparse_does_not_duplicate_advance_deduction(self):
        """_generate_deductions called twice produces exactly one ADVANCE deduction."""
        advance = self._make_advance()
        advance.action_confirm()

        payslip = self._make_payslip()
        payslip._generate_deductions()
        payslip._generate_deductions()  # reparse / "Compute All" again

        advance_deductions = payslip.deduction_ids.filtered(
            lambda d: d.deduction_type_id.code == 'ADVANCE'
        )
        self.assertEqual(len(advance_deductions), 1)
        self.assertAlmostEqual(advance_deductions.amount, advance.amount, places=2)

    def test_advance_deduction_amount_equals_net_advance(self):
        """Deduction amount on payslip equals net advance (after taxes)."""
        advance = self._make_advance(wage_percent=50.0)
        advance.action_confirm()

        payslip = self._make_payslip()
        payslip._generate_deductions()

        deduction = payslip.deduction_ids.filtered(
            lambda d: d.deduction_type_id.code == 'ADVANCE'
        )
        self.assertTrue(deduction)
        self.assertAlmostEqual(deduction.amount, advance.amount, places=2)
        # Net advance, not gross
        self.assertLess(deduction.amount, advance.gross_amount)

