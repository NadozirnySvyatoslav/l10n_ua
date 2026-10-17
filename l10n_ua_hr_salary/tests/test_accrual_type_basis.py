"""Which shipped accrual types make the vacation average (#290).

Порядок № 100, п. 3 counts every accrued wage — bonuses and extra pay
included — and п. 4 names what stays out: one-off payments, social payments,
payments in kind. Vacation pay and sickness benefits are not in the flag:
the vacation average takes them by their category, the two-month average
does not take them at all.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestAccrualTypeBasis(TransactionCase):

    def _flag(self, xmlid):
        return self.env.ref('l10n_ua_hr_salary.%s' % xmlid).is_basic_salary

    def test_wage_types_are_in_the_average(self):
        for xmlid in ('accrual_type_salary', 'accrual_type_allowance',
                      'accrual_type_bonus', 'accrual_type_overtime',
                      'accrual_type_night', 'accrual_type_holiday',
                      'accrual_type_indexation', 'accrual_type_seniority',
                      'accrual_type_piece', 'accrual_type_retro'):
            self.assertTrue(self._flag(xmlid), xmlid)

    def test_paragraph_4_payments_are_not(self):
        for xmlid in ('accrual_type_compensation', 'accrual_type_severance',
                      'accrual_type_material_aid', 'accrual_type_in_kind',
                      'accrual_type_maternity', 'accrual_type_vacation',
                      'accrual_type_sick_employer', 'accrual_type_sick_fss'):
            self.assertFalse(self._flag(xmlid), xmlid)

    def test_a_new_type_is_in_the_average(self):
        kind = self.env['hr.accrual.type'].create({
            'name': 'Доплата за суміщення', 'code': 'TEST290_COMBINE',
            'category': 'allowance',
        })
        self.assertTrue(kind.is_basic_salary)
