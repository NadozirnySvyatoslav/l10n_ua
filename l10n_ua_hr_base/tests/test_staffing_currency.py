"""The staffing line's currency is the money of its own company.

`currency_id` defaulted to `self.env.company.currency_id` — the company in the
switcher, not the one on the line — and the field is invisible on the form for
everybody outside multi-currency. A line written for company A while the
officer was looking at company B took B's money over A's number, and nothing
on the screen said so. Downstream it either multiplied the salary by the rate
on its way into a payslip, or stopped the calculation months later with a
message about currency rates that named no staffing line.
"""

import importlib.util
import os
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestStaffingCurrency(TestHrUaBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')
        cls.company.currency_id = cls.uah
        # The company in the switcher throughout: it keeps its books in
        # another currency, which is the whole of the trouble.
        cls.foreign_company = cls.env['res.company'].create({
            'name': 'Test Foreign Company',
            'currency_id': cls.usd.id,
        })
        cls.env['res.currency.rate'].create({
            'name': '2026-01-01',
            'currency_id': cls.usd.id,
            'company_id': cls.company.id,
            'inverse_company_rate': 40.0,
        })
        # A currency nothing can convert: no rate for it anywhere, which is
        # what makes a line naming it broken rather than merely unusual.
        cls.unknown = cls.env['res.currency'].search(
            [('name', '=', 'ZZZ')], limit=1) or cls.env['res.currency'].create(
                {'name': 'ZZZ', 'symbol': 'Z'})

    def _line(self, **overrides):
        """A line for `self.company`, written from the other company's desk."""
        vals = {
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'units': 1.0,
            'salary': 20000.0,
            'date_from': date(2026, 1, 1),
            'state': 'approved',
        }
        vals.update(overrides)
        return self.env['hr.staffing.table'].with_company(
            self.foreign_company).create(vals)

    def test_the_line_takes_the_currency_of_its_own_company(self):
        """The bug itself: the switcher decided, and the line paid for it."""
        self.assertEqual(self._line().currency_id, self.uah)

    def test_the_salary_is_not_converted_on_its_way_into_payroll(self):
        """What the wrong currency did further down — 20 000 became 800 000."""
        line = self._line()

        self.assertAlmostEqual(
            line._salary_in_company_currency(date(2026, 6, 1)), 20000.0,
            places=2)

    def test_an_explicit_currency_is_not_overwritten(self):
        """A position priced in another currency stays priced in it.

        The default is what was wrong, not the possibility:
        `_salary_in_company_currency` exists for this line.
        """
        line = self._line(currency_id=self.usd.id)

        self.assertEqual(line.currency_id, self.usd)
        self.assertAlmostEqual(
            line._salary_in_company_currency(date(2026, 6, 1)), 800000.0,
            places=2)

    def test_the_currency_follows_the_line_to_another_company(self):
        """Moving the line re-states its salary in the new company's money.

        The figure keeps its number and changes its meaning, so the field is
        tracked and the note below says it out loud.
        """
        line = self._line()

        line.company_id = self.foreign_company

        self.assertEqual(line.currency_id, self.usd)

    def test_a_currency_with_no_rate_anywhere_is_refused(self):
        """Refused here, where it can be corrected — not on a payslip.

        `_salary_in_company_currency` would raise on the first payslip to reach
        this position, months later, in a message that names no staffing line.
        """
        with self.assertRaises(ValidationError):
            self._line(currency_id=self.unknown.id)

    def test_a_line_with_no_salary_yet_is_not_refused(self):
        """A draft being filled in is not a mistake to stop."""
        line = self._line(salary=0.0, currency_id=self.unknown.id, state='draft')

        self.assertEqual(line.currency_id, self.unknown)

    def test_a_foreign_currency_leaves_a_note_in_the_chatter(self):
        """The routes an onchange never sees: import, data file, `create()`."""
        line = self._line(currency_id=self.usd.id)

        self.assertTrue(any(
            'USD' in (message.body or '') for message in line.message_ids),
            'a line stating its salary in another currency should say so in '
            'its own chatter')

    def test_the_note_is_not_left_on_an_ordinary_line(self):
        line = self._line()

        self.assertFalse(any(
            'USD' in (message.body or '') for message in line.message_ids))

    def test_the_form_warns_before_the_line_is_saved(self):
        draft = self.env['hr.staffing.table'].new({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'currency_id': self.usd.id,
            'salary': 20000.0,
        })

        self.assertIn('warning', draft._onchange_currency_id() or {})

    def test_the_form_says_nothing_about_the_company_s_own_money(self):
        draft = self.env['hr.staffing.table'].new({
            'company_id': self.company.id,
            'currency_id': self.uah.id,
            'salary': 20000.0,
        })

        self.assertFalse(draft._onchange_currency_id())


@tagged('post_install', '-at_install')
class TestStaffingCurrencyMigration(TestHrUaBase):
    """19.0.1.7.0: the lines the default had already spoiled.

    They cannot be created through the ORM any more — the constraint refuses
    the unconvertible ones — so the rows are put in place the way the database
    holds them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')
        cls.company.currency_id = cls.uah
        cls.unknown = cls.env['res.currency'].search(
            [('name', '=', 'ZZZ')], limit=1) or cls.env['res.currency'].create(
                {'name': 'ZZZ', 'symbol': 'Z'})

        path = os.path.join(
            os.path.dirname(__file__), '..', 'migrations', '20.0.1.7.0',
            'post-migration.py')
        spec = importlib.util.spec_from_file_location(
            'l10n_ua_hr_base_20_1_7_0_post', path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def _line(self, currency, job=None):
        line = self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': (job or self.job).id,
            'units': 1.0,
            'salary': 20000.0,
            'date_from': date(2026, 1, 1),
        })
        # Flushed first: the currency is computed on create and only reaches
        # the column at flush time, which would otherwise land after this
        # UPDATE and write the correct value back over it.
        self.env.flush_all()
        self.env.cr.execute(
            'UPDATE hr_staffing_table SET currency_id = %s WHERE id = %s',
            (currency.id if currency else None, line.id))
        self.env.invalidate_all()
        return line

    def test_a_salary_nothing_could_convert_was_hryvnia_all_along(self):
        """No rate for that currency, ever: the number was never converted.

        Whatever the currency said, the figure was entered, read and printed
        as the company's own money — and every payslip that reached the
        position stopped rather than convert it.
        """
        line = self._line(self.unknown)

        self.script.migrate(self.env.cr, '19.0.1.6.0')

        self.assertEqual(line.currency_id, self.uah)
        self.assertTrue(any(
            'ZZZ' in (message.body or '') for message in line.message_ids))

    def test_a_salary_a_rate_exists_for_is_reported_and_left_alone(self):
        """Forty times somebody's salary is not a guess to make in a script."""
        self.env['res.currency.rate'].create({
            'name': '2026-01-01',
            'currency_id': self.usd.id,
            'company_id': self.company.id,
            'inverse_company_rate': 40.0,
        })
        line = self._line(self.usd)

        self.script.migrate(self.env.cr, '19.0.1.6.0')

        self.assertEqual(line.currency_id, self.usd)
        self.assertTrue(any(
            'USD' in (message.body or '') for message in line.message_ids),
            'a line left as it is should carry the reason in its chatter')

    def test_a_line_that_named_no_currency_gets_the_company_s(self):
        """Rows the default never reached at all — an import, or plain SQL.

        Nothing converted those either: a line with no currency hands payroll
        its figure untouched, which is the company's own money by default and
        by accident at the same time.
        """
        line = self._line(None)

        self.script.migrate(self.env.cr, '19.0.1.6.0')

        self.assertEqual(line.currency_id, self.uah)
        self.assertTrue(any(
            'UAH' in (message.body or '') for message in line.message_ids))

    def test_a_fresh_install_is_left_alone(self):
        line = self._line(self.unknown)

        self.script.migrate(self.env.cr, None)

        self.assertEqual(line.currency_id, self.unknown)
