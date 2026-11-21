"""Tests for execution-document withholding limits — issue #147.

Cover:
- collected_amount / remaining_amount computed from posted payslip deductions
- 50/70% legal ceiling on total execution-document deductions (after taxes)
- priority ordering across several documents
- gradual repayment of a finite debt across periods
"""

from datetime import date
from odoo.tests import tagged
from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestExecutionDocumentLimit(SalaryTestCase):
    """Integration tests for hr.execution.document deduction generation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Auto-generated execution deductions need an ALIMONY deduction type.
        cls.alimony_type = cls.env['hr.deduction.type'].search([
            ('code', '=', 'ALIMONY'),
        ], limit=1)
        if not cls.alimony_type:
            cls.alimony_type = cls.env['hr.deduction.type'].create({
                'name': 'Аліменти',
                'code': 'ALIMONY',
                'category': 'alimony',
                'calculation_method': 'percent_net',
            })

    def _exec_doc(self, **kwargs):
        vals = {
            'name': 'ВД-LIM/2025',
            'employee_id': self.employee.id,
            'document_type': 'alimony',
            'calculation_method': 'percent',
            'percent_value': 25.0,
            'date_from': date(2025, 1, 1),
            'recipient_name': 'Отримувач',
            'company_id': self.company.id,
            'state': 'active',
        }
        vals.update(kwargs)
        return self.env['hr.execution.document'].create(vals)

    def _payslip(self, month, amount=25000):
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 28),
            'company_id': self.company.id,
        })
        self.env['hr.payslip.accrual'].create({
            'payslip_id': payslip.id,
            'accrual_type_id': self.accrual_wage.id,
            'quantity': 1,
            'rate': amount,
            'amount': amount,
        })
        return payslip

    def _exec_deductions(self, payslip):
        return payslip.deduction_ids.filtered('execution_doc_id')

    def test_single_document_within_limit(self):
        """A lone 25% alimony order stays well under the ceiling and is taken in full."""
        self._exec_doc(percent_value=25.0, max_deduction_percent=70.0)
        payslip = self._payslip(6)
        payslip.action_compute_sheet()
        deds = self._exec_deductions(payslip)
        self.assertEqual(len(deds), 1)
        # Alimony is a share of the income after ПДФО and військовий збір.
        net_after_tax = (payslip.gross_salary - payslip.pdfo_amount
                         - payslip.military_tax_amount)
        self.assertGreater(payslip.pdfo_amount, 0)
        self.assertAlmostEqual(deds.amount, round(net_after_tax * 0.25, 2), places=2)
        self.assertAlmostEqual(deds.base_amount, net_after_tax, places=2)
        self.assertLess(deds.amount, payslip.gross_salary * 0.25)

    def test_cumulative_ceiling_enforced_by_priority(self):
        """Two orders that jointly exceed 70% net: priority 1 is paid, priority 3 is capped."""
        self._exec_doc(name='ВД-A', percent_value=50.0, deduction_priority='1',
                       max_deduction_percent=70.0)
        self._exec_doc(name='ВД-B', percent_value=50.0, deduction_priority='3',
                       max_deduction_percent=50.0)
        payslip = self._payslip(6)
        payslip.action_compute_sheet()

        net_after_tax = (payslip.gross_salary - payslip.pdfo_amount
                         - payslip.military_tax_amount)
        ceiling = round(net_after_tax * 0.70, 2)  # cap = max(70, 50)

        deds = self._exec_deductions(payslip)
        total = sum(deds.mapped('amount'))
        self.assertAlmostEqual(total, ceiling, places=2,
                               msg='Total withholding must equal the 70% ceiling')

        by_doc = {d.execution_doc_id.name: d.amount for d in deds}
        # Priority-1 order gets its full 50% of the income after taxes;
        # priority-3 gets the leftover.
        self.assertAlmostEqual(by_doc['ВД-A'], round(net_after_tax * 0.50, 2), places=2)
        self.assertLess(by_doc['ВД-B'], by_doc['ВД-A'])

    def test_finite_debt_repaid_gradually(self):
        """A fixed-amount debt is collected across periods and stops when settled."""
        doc = self._exec_doc(calculation_method='fixed', fixed_amount=3000.0,
                             total_amount=5000.0, deduction_priority='1',
                             max_deduction_percent=70.0)

        # Period 1: full 3000 taken, 2000 remains after posting.
        p1 = self._payslip(6)
        p1.action_compute_sheet()
        self.assertAlmostEqual(self._exec_deductions(p1).amount, 3000.0, places=2)
        p1.action_payslip_done()
        self.assertAlmostEqual(doc.collected_amount, 3000.0, places=2)
        self.assertAlmostEqual(doc.remaining_amount, 2000.0, places=2)

        # Period 2: only the outstanding 2000 may be taken, not the full 3000.
        p2 = self._payslip(7)
        p2.action_compute_sheet()
        self.assertAlmostEqual(self._exec_deductions(p2).amount, 2000.0, places=2)
        p2.action_payslip_done()
        self.assertAlmostEqual(doc.collected_amount, 5000.0, places=2)
        self.assertAlmostEqual(doc.remaining_amount, 0.0, places=2)

        # Period 3: debt settled → nothing generated.
        p3 = self._payslip(8)
        p3.action_compute_sheet()
        self.assertFalse(self._exec_deductions(p3))

    def test_draft_payslip_not_counted_as_collected(self):
        """collected_amount reflects only posted (done) payslips."""
        doc = self._exec_doc(calculation_method='fixed', fixed_amount=1000.0,
                             total_amount=5000.0)
        payslip = self._payslip(6)
        payslip.action_compute_sheet()
        # Still draft — nothing collected yet.
        self.assertAlmostEqual(doc.collected_amount, 0.0, places=2)
        payslip.action_payslip_done()
        self.assertAlmostEqual(doc.collected_amount, 1000.0, places=2)
