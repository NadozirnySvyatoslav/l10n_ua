"""Tests for the unused-vacation compensation phrase on dismissal orders — issue #125.

They cover what this module owns — the template, the printed order and the
flag that drives them — and set the day count by hand, so they run on a plain
install of l10n_ua_hr_documents. The day count itself comes from the vacation
entitlement of l10n_ua_hr_holidays and is tested there
(test_vacation_entitlement).
"""

import re
from datetime import date
from odoo.tests import TransactionCase, tagged


class VacationCompensationCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Звільнюваний Працівник',
            'company_id': cls.company.id,
        })

    def _dismissal(self, dismissal_date, days=None, **kwargs):
        vals = {
            'order_type': 'dismissal',
            'date': dismissal_date,
            'date_dismissal': dismissal_date,
            'employee_id': self.employee.id,
            'subject': 'Звільнення',
        }
        vals.update(kwargs)
        order = self.env['hr.order'].create(vals)
        if days is not None:
            # Written after create so the value wins over the compute the way
            # a hand-entered figure does — the field is stored but editable.
            order.unused_vacation_days = days
        return order

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

    def _print(self, order):
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_hr_documents.report_hr_order', order.ids)[0]
        return html.decode() if isinstance(html, bytes) else html

    def _plain_text(self, html):
        return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


@tagged('post_install', '-at_install')
class TestVacationCompensation(VacationCompensationCommon):

    def test_phrase_rendered_in_report(self):
        """The standard compensation sentence appears in the printed order."""
        order = self._dismissal(date(2026, 5, 20), days=7)
        text = self._print(order)
        self.assertIn('виплатити компенсацію', text)
        self.assertIn('невикористаної відпустки', text)

    def test_phrase_suppressed_when_disabled(self):
        """No phrase in the printed order when the flag is off."""
        order = self._dismissal(date(2026, 5, 20), days=7,
                                include_vacation_compensation=False)
        self.assertNotIn('виплатити компенсацію', self._print(order))

    def test_phrase_suppressed_without_days(self):
        """No phrase in the printed order when there is nothing to compensate."""
        order = self._dismissal(date(2026, 5, 20), days=0)
        self.assertNotIn('виплатити компенсацію', self._print(order))

    def test_phrase_rendered_in_loaded_template(self):
        """Loading the dismissal template writes the compensation sentence,
        with the days substituted, right under the basis line."""
        order = self._dismissal(date(2026, 5, 20), days=7)
        text = self._plain_text(self._apply_dismissal_template(order))
        self.assertIn(
            'Бухгалтерії підприємства виплатити компенсацію за 7 '
            'календарних днів невикористаної відпустки.', text)
        self.assertLess(
            text.index('Підстава'),
            text.index('Бухгалтерії підприємства виплатити компенсацію'),
            'The compensation line must follow the basis line.')

    def test_phrase_absent_from_loaded_template_when_disabled(self):
        """No compensation sentence in the loaded template when the flag is off."""
        order = self._dismissal(date(2026, 5, 20), days=7,
                                include_vacation_compensation=False)
        content = self._apply_dismissal_template(order)
        self.assertNotIn('виплатити компенсацію', content)

    def test_phrase_absent_from_loaded_template_without_days(self):
        """Nothing to compensate — no sentence, even with the flag on. Same
        rule as the printed report."""
        order = self._dismissal(date(2026, 5, 20), days=0)
        content = self._apply_dismissal_template(order)
        self.assertNotIn('виплатити компенсацію', content)

    def test_manual_day_count_reaches_the_template(self):
        """The template quotes the figure standing on the order at load time,
        including one typed over the computed value."""
        order = self._dismissal(date(2026, 5, 20), days=5)
        text = self._plain_text(self._apply_dismissal_template(order))
        self.assertIn('виплатити компенсацію за 5 календарних днів', text)

    def test_day_count_agrees_with_the_noun(self):
        """Наказ — офіційний документ: «1 календарний день», «2 календарні
        дні», «5 календарних днів», з винятками 11–14."""
        order = self._dismissal(date(2026, 5, 20), days=0)
        for days, phrase in ((1, '1 календарний день'),
                             (3, '3 календарні дні'),
                             (5, '5 календарних днів'),
                             (11, '11 календарних днів'),
                             (12, '12 календарних днів'),
                             (21, '21 календарний день'),
                             (24, '24 календарні дні')):
            order.unused_vacation_days = days
            self.assertEqual(order.unused_vacation_days_phrase(), phrase)

    def test_fractional_days_round_up_in_favour_of_the_employee(self):
        """Дробові дні — вгору: 0.4 → 1 день (фраза є), 11.3 → 12, ціле лишається цілим."""
        order = self._dismissal(date(2026, 5, 20), days=0.4)
        self.assertIn('за 1 календарний день', self._plain_text(
            self._print(order)))
        order.unused_vacation_days = 11.3
        self.assertIn('за 12 календарних днів', self._plain_text(
            self._apply_dismissal_template(order)))
        order.unused_vacation_days = 12.0
        self.assertEqual(order.unused_vacation_days_phrase(),
                         '12 календарних днів')

    def test_non_dismissal_has_no_days(self):
        """A non-dismissal order never computes compensation days."""
        order = self.env['hr.order'].create({
            'order_type': 'bonus',
            'date': date(2026, 5, 20),
            'employee_id': self.employee.id,
            'subject': 'Премія',
        })
        self.assertEqual(order.unused_vacation_days, 0)
