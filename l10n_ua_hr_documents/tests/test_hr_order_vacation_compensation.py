"""Tests for the unused-vacation compensation phrase on dismissal orders — issue #125."""

import re
from datetime import date
from unittest import SkipTest
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVacationCompensation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.vacation.balance' not in cls.env:
            raise SkipTest('l10n_ua_hr_holidays not installed')
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Звільнюваний Працівник',
            'company_id': cls.company.id,
        })
        # Own leave type instead of "whatever comes first in the database":
        # the result depends on the type's transfer rules, so picking an
        # arbitrary one made the outcome depend on the installed modules.
        # Non-transferable keeps each year's days inside their own period,
        # which is what the year-scoping test below is about; carry-over is
        # covered separately by test_transferable_type_carries_previous_years.
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Annual Basic (compensation test)',
            'is_transferable': False,
        })

    def _balance(self, year, entitled):
        return self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': year,
            'entitled_days': entitled,
        })

    def _dismissal(self, dismissal_date, **kwargs):
        vals = {
            'order_type': 'dismissal',
            'date': dismissal_date,
            'date_dismissal': dismissal_date,
            'employee_id': self.employee.id,
            'subject': 'Звільнення',
        }
        vals.update(kwargs)
        return self.env['hr.order'].create(vals)

    def test_unused_days_computed_from_balance(self):
        """unused_vacation_days is pulled from the dismissal-year balance."""
        self._balance(2026, 12)
        order = self._dismissal(date(2026, 5, 20))
        self.assertAlmostEqual(order.unused_vacation_days, 12, places=2)

    def test_days_scoped_to_dismissal_year(self):
        """Only the dismissal year's balance counts, not other years. A later
        year is used here so the check is not confounded by carry-over: unused
        days flow forward (dismissal year -> future), never back, so the 2027
        balance must not be summed into the 2026 compensation."""
        self._balance(2026, 3)
        self._balance(2027, 8)
        order = self._dismissal(date(2026, 7, 1))
        self.assertAlmostEqual(order.unused_vacation_days, 3, places=2)

    def test_transferable_type_carries_previous_years(self):
        """A transferable type rolls last year's unused days into the
        dismissal year, and they are compensated too.

        Art. 24 of the Vacation Law requires compensating every unused day,
        not only the dismissal year's entitlement. The year-scoped search
        still holds: the older balance is not counted twice, its remainder
        reaches the total through carried_over.
        """
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Annual Basic transferable (compensation test)',
            'is_transferable': True,
        })
        for year, days in ((2025, 8), (2026, 3)):
            self.env['hr.vacation.balance'].create({
                'employee_id': self.employee.id,
                'leave_type_id': leave_type.id,
                'year': year,
                'entitled_days': days,
            })
        order = self._dismissal(date(2026, 7, 1))
        self.assertAlmostEqual(order.unused_vacation_days, 11, places=2)

    def test_manual_override_persists(self):
        """A hand-entered day count is kept (field is editable)."""
        self._balance(2026, 12)
        order = self._dismissal(date(2026, 5, 20))
        order.unused_vacation_days = 5
        self.assertAlmostEqual(order.unused_vacation_days, 5, places=2)

    def test_phrase_rendered_in_report(self):
        """The standard compensation sentence appears in the printed order."""
        self._balance(2026, 7)
        order = self._dismissal(date(2026, 5, 20))
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_hr_documents.report_hr_order', order.ids)[0]
        text = html.decode() if isinstance(html, bytes) else html
        self.assertIn('виплатити компенсацію', text)
        self.assertIn('невикористаної відпустки', text)

    def test_phrase_suppressed_when_disabled(self):
        """No phrase when the flag is off."""
        self._balance(2026, 7)
        order = self._dismissal(date(2026, 5, 20), include_vacation_compensation=False)
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_hr_documents.report_hr_order', order.ids)[0]
        text = html.decode() if isinstance(html, bytes) else html
        self.assertNotIn('виплатити компенсацію', text)

    def _apply_dismissal_template(self, order):
        """Run the "Load Template" flow the user goes through on the form."""
        template = self.env.ref(
            'l10n_ua_hr_documents.order_template_dismissal')
        wizard = self.env['hr.order.template.wizard'].create({
            'order_id': order.id,
            'order_type': order.order_type,
            'template_id': template.id,
        })
        wizard.action_apply_template()
        return order.content or ''

    def test_phrase_rendered_in_loaded_template(self):
        """Loading the dismissal template writes the compensation sentence,
        with the days substituted, right under the "Підстава" line."""
        self._balance(2026, 7)
        order = self._dismissal(date(2026, 5, 20))
        content = self._apply_dismissal_template(order)
        text = ' '.join(re.sub(r'<[^>]+>', ' ', content).split())
        self.assertIn(
            'Бухгалтерії підприємства виплатити компенсацію за 7 '
            'календарних днів невикористаної відпустки.', text)
        self.assertLess(
            text.index('Підстава'),
            text.index('Бухгалтерії підприємства виплатити компенсацію'),
            'The compensation line must follow the "Підстава" line.')

    def test_phrase_absent_from_loaded_template_when_disabled(self):
        """No compensation sentence in the loaded template when the flag is off."""
        self._balance(2026, 7)
        order = self._dismissal(date(2026, 5, 20),
                                include_vacation_compensation=False)
        content = self._apply_dismissal_template(order)
        self.assertNotIn('виплатити компенсацію', content)

    def test_phrase_absent_from_loaded_template_without_days(self):
        """Nothing to compensate — no sentence, even with the flag on. Same
        rule as the printed report."""
        order = self._dismissal(date(2026, 5, 20), unused_vacation_days=0)
        content = self._apply_dismissal_template(order)
        self.assertEqual(order.unused_vacation_days, 0)
        self.assertNotIn('виплатити компенсацію', content)

    def test_non_dismissal_has_no_days(self):
        """A non-dismissal order never computes compensation days."""
        self._balance(2026, 10)
        order = self.env['hr.order'].create({
            'order_type': 'bonus',
            'date': date(2026, 5, 20),
            'employee_id': self.employee.id,
            'subject': 'Премія',
        })
        self.assertEqual(order.unused_vacation_days, 0)
