"""#505 — вихідна допомога при звільненні (ст. 44 КЗпП, Порядок № 100)."""

from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestSeverance(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salary = cls.env['hr.accrual.type'].search([('code', '=', 'SALARY')], limit=1)
        cls.reduction = cls.env.ref('l10n_ua_hr_contract.termination_reason_reduction')
        cls.military = cls.env.ref('l10n_ua_hr_contract.termination_reason_military')
        cls.own_will = cls.env.ref('l10n_ua_hr_contract.termination_reason_own_will')
        # Квітень: 21 робочий день, відпрацьовано 20, 24 000 грн;
        # травень: 20 робочих днів, відпрацьовано 20, 25 000 грн.
        cls._done_slip(4, 30, 21, 20, 24000)
        cls._done_slip(5, 31, 20, 20, 25000)

    @classmethod
    def _done_slip(cls, month, last, scheduled, worked, amount):
        slip = cls.env['hr.payslip'].create({
            'employee_id': cls.employee.id, 'version_id': cls.version.id,
            'date_from': date(2025, month, 1), 'date_to': date(2025, month, last),
        })
        cls.env['hr.payslip.accrual'].create({
            'payslip_id': slip.id, 'accrual_type_id': cls.salary.id,
            'quantity': 1, 'rate': amount, 'amount': amount,
        })
        slip.write({'scheduled_days': scheduled, 'worked_days': worked, 'state': 'done'})
        return slip

    def _dismiss(self, reason, on=date(2025, 6, 20)):
        self.version.write({'contract_date_end': on, 'termination_reason_ua_id': reason.id})

    def _june_slip(self):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'version_id': self.version.id,
            'date_from': date(2025, 6, 1), 'date_to': date(2025, 6, 30),
        })
        slip.write({'scheduled_hours': 160.0, 'scheduled_days': 20, 'worked_days': 14,
                    'worked_hours': 112.0})
        slip._generate_accruals()
        return slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == 'SEVERANCE')

    def test_average_monthly_earnings_two_months(self):
        # (24 000 + 25 000) / 40 відпрацьованих днів × (21 + 20) / 2 = 25 112,50.
        slip = self.env['hr.payslip'].new({
            'employee_id': self.employee.id, 'version_id': self.version.id})
        self.assertAlmostEqual(slip._average_monthly_earnings(date(2025, 6, 20)), 25112.5)

    def test_reduction_pays_one_average_month(self):
        self._dismiss(self.reduction)
        severance = self._june_slip()
        self.assertEqual(len(severance), 1)
        self.assertAlmostEqual(severance.amount, 25112.5)
        self.assertFalse(severance.accrual_type_id.is_esv_base)
        self.assertTrue(severance.accrual_type_id.is_taxable_pdfo)

    def test_conscription_pays_two_minimum_wages(self):
        self._dismiss(self.military)
        severance = self._june_slip()
        self.assertAlmostEqual(severance.amount, 2 * self.psp_params.min_wage)

    def test_own_will_pays_nothing(self):
        self._dismiss(self.own_will)
        self.assertFalse(self._june_slip())

    def test_dismissal_outside_period_pays_nothing(self):
        self._dismiss(self.reduction, on=date(2025, 7, 15))
        self.assertFalse(self._june_slip())

    def test_manual_severance_not_doubled(self):
        self._dismiss(self.reduction)
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'version_id': self.version.id,
            'date_from': date(2025, 6, 1), 'date_to': date(2025, 6, 30),
        })
        severance_type = self.env['hr.accrual.type'].search([('code', '=', 'SEVERANCE')], limit=1)
        self.env['hr.payslip.accrual'].create({
            'payslip_id': slip.id, 'accrual_type_id': severance_type.id,
            'quantity': 1, 'rate': 30000, 'amount': 30000})
        slip.write({'scheduled_hours': 160.0, 'scheduled_days': 20, 'worked_days': 14,
                    'worked_hours': 112.0})
        slip._generate_accruals()
        severance = slip.accrual_ids.filtered(lambda a: a.accrual_type_id == severance_type)
        self.assertEqual(len(severance), 1)
        self.assertEqual(severance.amount, 30000)
