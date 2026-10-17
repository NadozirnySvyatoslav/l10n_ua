"""The averages read the benefits a payslip now accrues as they should.

A payslip pays the days of a sickness or a maternity leave by their own
lines. The sick-leave average leaves those lines out with their days; the
vacation average keeps the sickness benefits and their days, and leaves out
the maternity benefit with its days. A payslip without such lines — every
month closed before they existed — is read as before.
"""
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestAverageBenefits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.UAH')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Average Benefits Employee',
            'company_id': cls.company.id,
        })
        LeaveType = cls.env['hr.leave.type']
        common = {'is_calendar_days': True, 'requires_allocation': False,
                  'company_id': cls.company.id}
        cls.vacation_type = LeaveType.create(dict(
            common, name='Additional Leave (benefits test)',
            ua_leave_category='annual_additional', is_paid=True))
        cls.sick_type = LeaveType.create(dict(
            common, name='Sick Leave (benefits test)',
            ua_leave_category='sick', is_paid=True))

    def setUp(self):
        super().setUp()
        if 'hr.payslip' not in self.env:
            self.skipTest('l10n_ua_hr_salary is not installed')

    def _payslip(self, month, lines):
        """A closed payslip of the month with [(code, amount, days)]."""
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': month,
            'date_to': month + relativedelta(months=1, days=-1),
        })
        for code, amount, days in lines:
            kind = self.env['hr.accrual.type'].search([('code', '=', code)], limit=1)
            self.env['hr.payslip.accrual'].create({
                'payslip_id': slip.id, 'accrual_type_id': kind.id,
                'quantity': days, 'rate': amount / days if days else amount,
                'amount': amount,
            })
        slip.state = 'done'
        return slip

    # Sick leave

    def _sick_average(self):
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 15),
            'date_to': date(2026, 6, 20),
        })
        return sick._calculate_average_salary()

    def test_sick_average_leaves_out_earlier_benefits_with_their_days(self):
        # March: 31 days, 7 of them on a sickness paid by its benefits.
        # February, closed before benefits were accrued: read as before.
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 24000, 1), ('SICK_EMP', 5000, 5), ('SICK_FSS', 2000, 2)])
        self._payslip(date(2026, 2, 1), [('SALARY', 28000, 1)])
        self.assertAlmostEqual(self._sick_average(),
                               round((24000 + 28000) / (24 + 28), 2), places=2)

    def test_sick_average_leaves_out_a_maternity_benefit_with_its_days(self):
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 11000, 1), ('MATERNITY', 20000, 20)])
        self.assertAlmostEqual(self._sick_average(), 1000.0, places=2)

    def test_sick_average_takes_the_contribution_base(self):
        # Порядок № 1266, п. 3: the material aid is outside the contribution
        # base and stays out; the compensation for unused vacation and the
        # bonus are in it and count.
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 20000, 1), ('BONUS', 4800, 1),
            ('COMP_VAC', 6200, 1), ('MAT_AID', 5000, 1)])
        self.assertAlmostEqual(self._sick_average(),
                               round(31000 / 31, 2), places=2)

    # Vacation

    def _vacation(self):
        return self.env['hr.leave'].create({
            'name': 'Vacation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.vacation_type.id,
            'date_from': datetime(2026, 6, 15, 8, 0, 0),
            'date_to': datetime(2026, 6, 21, 17, 0, 0),
        })

    def _vacation_days(self, leave):
        """Calendar days of the vacation period less its public holidays, read
        the way the average reads them."""
        date_to = leave.date_from.date() - relativedelta(days=1)
        date_from = date_to - relativedelta(months=12) + relativedelta(days=1)
        holidays = self.env['resource.calendar.leaves'].search_count([
            ('resource_id', '=', False),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
        ])
        return (date_to - date_from).days + 1 - holidays

    def test_vacation_average_keeps_sickness_benefits_and_their_days(self):
        # The sickness of March is a validated time off; its days stay in the
        # divisor, since its benefit is in the earnings.
        sick = self.env['hr.leave'].create({
            'name': 'Sickness',
            'employee_id': self.employee.id,
            'holiday_status_id': self.sick_type.id,
            'request_date_from': date(2026, 3, 9),
            'request_date_to': date(2026, 3, 15),
        })
        sick._action_validate()
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 20000, 1), ('SICK_EMP', 2500, 5), ('SICK_FSS', 1000, 2)])
        leave = self._vacation()
        self.assertAlmostEqual(
            leave._calculate_average_salary(),
            round(23500 / self._vacation_days(leave), 2), places=2)

    def test_vacation_average_leaves_out_a_maternity_benefit_with_its_days(self):
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 20000, 1), ('MATERNITY', 9000, 30)])
        leave = self._vacation()
        self.assertAlmostEqual(
            leave._calculate_average_salary(),
            round(20000 / (self._vacation_days(leave) - 30), 2), places=2)

    def test_vacation_average_takes_basic_salary_only(self):
        # Порядок № 100: the bonus and the extra pay count (п. 3); the
        # compensation for unused vacation, the material aid, the severance
        # pay and the income in kind do not (п. 4).
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 20000, 1), ('BONUS', 3000, 1), ('NIGHT', 700, 1),
            ('SENIORITY', 2000, 1), ('COMP_VAC', 6000, 1),
            ('MAT_AID', 5000, 1), ('SEVERANCE', 9000, 1), ('INKIND', 400, 1)])
        leave = self._vacation()
        self.assertAlmostEqual(
            leave._calculate_average_salary(),
            round(25700 / self._vacation_days(leave), 2), places=2)

    def test_vacation_average_keeps_earlier_vacation_pay(self):
        # The pay of an earlier vacation counts for the next one (п. 3, the
        # last paragraph), though its type is not marked basic salary.
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 15000, 1), ('VACATION', 5000, 7)])
        leave = self._vacation()
        self.assertAlmostEqual(
            leave._calculate_average_salary(),
            round(20000 / self._vacation_days(leave), 2), places=2)

    def test_vacation_average_leaves_out_a_type_not_marked(self):
        kind = self.env['hr.accrual.type'].create({
            'name': 'Разова винагорода', 'code': 'TEST290_ONEOFF',
            'category': 'other', 'is_basic_salary': False,
        })
        self.assertTrue(kind)
        self._payslip(date(2026, 3, 1), [
            ('SALARY', 20000, 1), ('TEST290_ONEOFF', 3000, 1)])
        leave = self._vacation()
        self.assertAlmostEqual(
            leave._calculate_average_salary(),
            round(20000 / self._vacation_days(leave), 2), places=2)
