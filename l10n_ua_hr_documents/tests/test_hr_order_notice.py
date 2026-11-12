"""#505 — наказ про звільнення: строк попередження, згода профспілки,
підстава на картці працівника."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrOrderNotice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Коваль Ольга', 'company_id': cls.env.company.id})
        cls.employee.with_context(active_test=False).version_ids[:1].write({
            'contract_date_start': date(2025, 1, 1), 'contract_date_end': False})
        cls.reduction = cls.env.ref('l10n_ua_hr_contract.termination_reason_reduction')
        cls.own_will = cls.env.ref('l10n_ua_hr_contract.termination_reason_own_will')

    def _order(self, reason, dismissal, notice=False):
        return self.env['hr.order'].create({
            'order_type': 'dismissal', 'date': dismissal, 'date_dismissal': dismissal,
            'employee_id': self.employee.id, 'subject': 'Звільнення',
            'termination_reason_id': reason.id, 'date_notice': notice,
        })

    def test_short_notice_blocks_confirm(self):
        order = self._order(self.reduction, date(2026, 3, 15), notice=date(2026, 2, 1))
        self.assertEqual(order.notice_deadline, date(2026, 4, 1))
        self.assertTrue(order.notice_short)
        with self.assertRaisesRegex(UserError, 'notice period'):
            order.action_confirm()
        self.assertEqual(order.state, 'draft')

    def test_enough_notice_confirms_and_sets_reason(self):
        order = self._order(self.reduction, date(2026, 4, 1), notice=date(2026, 2, 1))
        self.assertFalse(order.notice_short)
        self.assertTrue(order.union_consent_required)
        self.assertTrue(order.severance_info)
        order.action_confirm()
        version = self.employee.with_context(active_test=False).version_ids[:1]
        self.assertEqual(version.termination_reason_ua_id, self.reduction)
        order.action_cancel()
        self.assertFalse(version.termination_reason_ua_id)

    def test_missing_notice_only_warns(self):
        order = self._order(self.reduction, date(2026, 3, 15))
        self.assertTrue(order.notice_missing)
        self.assertFalse(order.notice_short)
        order.action_confirm()
        self.assertEqual(order.state, 'confirmed')

    def test_employee_notice_not_checked(self):
        # Попередження за ст. 38 дає працівник: строк не блокує наказ.
        order = self._order(self.own_will, date(2026, 3, 5), notice=date(2026, 3, 1))
        self.assertFalse(order.notice_short)
        self.assertFalse(order.notice_missing)
        self.assertFalse(order.union_consent_required)
