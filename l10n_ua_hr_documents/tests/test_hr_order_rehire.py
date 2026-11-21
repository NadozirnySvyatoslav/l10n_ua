"""Hiring an employee again must not disturb the employment before it.

Reported case: an employee was dismissed by transfer to another company and
hired back as a concurrent job days later. The hiring order used to stamp its
number on the employee's CURRENT version — which, for a hiring that starts
later, is still the previous employment — and then match that same version by
the number it had just written, moving it onto the new period. Depending on
whether the new date was free, that either erased the previous contract
without a trace or failed on the database's unique date_version index.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

# Comfortably ahead of any test run: a version dated in the future is not the
# employee's current one, and core refreshes current_version_id only once a
# day. That lag is what the reported failure was built on.
FUTURE = date(2099, 3, 1)


@tagged('post_install', '-at_install')
class TestHrOrderRehire(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.job = cls.env['hr.job'].create({
            'name': 'Водій', 'company_id': cls.company.id})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Переведений Працівник',
            'company_id': cls.company.id,
        })
        cls.first_version = cls.employee.with_context(
            active_test=False).version_ids[:1]
        cls.first_version.write({
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })

    def _versions(self):
        return self.employee.with_context(active_test=False).version_ids

    def _dismiss(self, dismissal_date):
        order = self.env['hr.order'].create({
            'order_type': 'dismissal',
            'subject': 'Про припинення трудового договору (переведенням)',
            'employee_id': self.employee.id,
            'date': dismissal_date,
            'date_dismissal': dismissal_date,
            'company_id': self.company.id,
        })
        order.action_confirm()
        return order

    def _hire(self, date_start, date_order=None):
        return self.env['hr.order'].create({
            'order_type': 'hiring',
            'subject': 'Про прийняття на роботу за сумісництвом',
            'employee_id': self.employee.id,
            'date': date_order or date_start,
            'date_start': date_start,
            'employment_form': 'secondary',
            'company_id': self.company.id,
        })

    def test_rehire_the_next_day_opens_a_second_contract(self):
        """Dismissed on the 30th, hired again on the 1st: two contracts, the
        first one left exactly as the dismissal closed it."""
        self._dismiss(date(2025, 6, 30))

        order = self._hire(date(2025, 7, 1))

        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))
        self.assertEqual(len(self._versions()), 2)
        new_version = self._versions() - self.first_version
        self.assertEqual(new_version.contract_date_start, date(2025, 7, 1))
        self.assertFalse(new_version.contract_date_end)
        self.assertEqual(new_version.hire_order_number, order.name)

    def test_order_fills_in_the_version_prepared_for_its_date(self):
        """The reported failure. The contract version for the hire date is
        already there, prepared by hand; the order has to fill that one in.
        Moving another version onto its date is what the database refused with
        "duplicate key ... (employee_id, date_version)"."""
        self._dismiss(date(2025, 6, 30))
        prepared = self.employee.sudo().create_version({
            'date_version': FUTURE,
            'contract_date_start': FUTURE,
        })

        order = self._hire(FUTURE)

        prepared.invalidate_recordset()
        self.assertEqual(prepared.hire_order_number, order.name)
        self.assertEqual(prepared.date_version, FUTURE)
        self.assertEqual(len(self._versions()), 2, 'no duplicate version')
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))

    def test_order_number_left_on_a_foreign_version_is_cleared(self):
        """Cards already carrying the order number on the wrong version — the
        damage the old sync did — heal on the next save instead of sending the
        order back to that version."""
        self._dismiss(date(2025, 6, 30))
        order = self._hire(date(2025, 7, 1))
        self.first_version.sudo().write({'hire_order_number': order.name})

        order.job_id = self.job

        self.first_version.invalidate_recordset()
        self.assertFalse(self.first_version.hire_order_number)
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))
        self.assertEqual(len(self._versions()), 2)

    def test_correcting_the_start_date_moves_the_order_own_version(self):
        """A date correction on the order follows through to the contract it
        opened, and to nothing else."""
        self._dismiss(date(2025, 6, 30))
        order = self._hire(date(2025, 7, 1))

        order.date_start = date(2025, 7, 15)

        version = self._versions().filtered(
            lambda v: v.hire_order_number == order.name)
        self.assertEqual(len(version), 1)
        self.assertEqual(version.date_version, date(2025, 7, 15))
        self.assertEqual(version.contract_date_start, date(2025, 7, 15))
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))
        self.assertEqual(len(self._versions()), 2)

    def test_same_day_rehire_is_refused_and_the_next_day_is_offered(self):
        """Hiring on the very day the previous contract ends overlaps it. The
        old sync went through by moving the previous contract onto that date,
        which is how the employment before it disappeared."""
        self._dismiss(date(2025, 6, 30))

        with self.assertRaises(UserError) as caught:
            self._hire(date(2025, 6, 30))

        message = str(caught.exception)
        self.assertIn('2025-06-30', message, 'names the contract in the way')
        self.assertIn('2025-07-01', message, 'offers the day after')
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))
        self.assertEqual(len(self._versions()), 1)

    def test_hiring_while_the_previous_contract_is_open_is_refused(self):
        """No dismissal recorded yet: the message has no next day to offer, so
        it says what to close first."""
        with self.assertRaises(UserError) as caught:
            self._hire(date(2025, 7, 1))

        message = str(caught.exception)
        self.assertIn('2025-01-01', message)
        self.assertNotIn('Details:', message,
                         'the generic sync failure says nothing useful here')
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_start, date(2025, 1, 1))

    def test_employee_card_shows_the_contract_the_order_opened(self):
        """current_version_id is stored and refreshed by a daily cron, so
        right after an order it can still point at the previous employment —
        the state the reported failure grew out of. The order refreshes it."""
        self._dismiss(date(2025, 6, 30))
        order = self._hire(date(2025, 7, 1))
        new_version = self._versions() - self.first_version
        # Simulate the cron lag: put the stale value back behind the ORM.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hr_employee SET current_version_id=%s WHERE id=%s",
            (self.first_version.id, self.employee.id))
        self.env.invalidate_all()

        order.job_id = self.job

        self.assertEqual(self.employee.current_version_id, new_version)

    def test_second_dismissal_closes_only_the_current_contract(self):
        """Once an employee holds two employments, writing an end date across
        both is something core refuses outright ("Cannot modify multiple
        versions contract dates with different contracts at once")."""
        self._dismiss(date(2025, 6, 30))
        self._hire(date(2025, 7, 1))

        second = self._dismiss(date(2025, 12, 31))

        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30),
                         'the previous employment keeps its own end date')
        new_version = self._versions() - self.first_version
        self.assertEqual(new_version.contract_date_end, date(2025, 12, 31))
        self.assertEqual(new_version.termination_order_number, second.name)

    def test_cancelling_a_dismissal_after_a_rehire_is_refused(self):
        """The dismissal cannot be taken back once the next employment has
        started: the contract it closed would run for ever, on top of the new
        one. The order says so instead of letting core answer with dates."""
        first = self._dismiss(date(2025, 6, 30))
        self._hire(date(2025, 7, 1))

        with self.assertRaises(UserError) as caught:
            first.action_cancel()

        self.assertIn('2025-07-01', str(caught.exception),
                      'names the contract that stands in the way')
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))
        self.assertEqual(first.state, 'confirmed', 'the order is left as it was')

    def test_cancelling_a_dismissal_reopens_only_what_it_closed(self):
        """Creating a version copies the termination number over, so a later
        employment can carry the number of the dismissal that ended the
        previous one. Cancelling by number alone would then reopen a period
        this order never closed — and fail, the two being different
        contracts."""
        first = self._dismiss(date(2025, 6, 30))
        untouched = self.employee.sudo().create_version({
            'date_version': date(2025, 3, 1),
        })
        untouched.sudo().write({'termination_order_number': first.name,
                                'contract_date_end': date(2025, 6, 30)})

        first.action_cancel()

        self.first_version.invalidate_recordset()
        self.assertFalse(self.first_version.contract_date_end,
                         'the period this order closed reopens')


    # --- Cards written by the old code -------------------------------------
    # The fixtures below are built the way the previous sync left them, partly
    # behind the ORM: the point is data the current code could not produce.

    def test_legacy_stale_number_on_an_older_employment_is_ignored(self):
        """The old dismissal stamped its number on EVERY version of the
        employee, so an earlier employment can still carry the number of an
        order that never ended it. Cancelling must go by the end date the
        order wrote, not by the number alone."""
        stale = self.employee.sudo().create_version({
            'date_version': date(2024, 1, 1)})
        self.env.flush_all()
        # Behind the ORM on purpose: this is what the previous code left, not
        # something the current one can produce.
        self.env.cr.execute(
            """UPDATE hr_version SET contract_date_start=%s, contract_date_end=%s,
               termination_order_number=%s WHERE id=%s""",
            (date(2024, 1, 1), date(2024, 12, 31), 'З-2025/0001', stale.id))
        self.env.invalidate_all()
        order = self.env['hr.order'].create({
            'order_type': 'dismissal', 'subject': 'Звільнення',
            'employee_id': self.employee.id, 'date': date(2025, 6, 30),
            'date_dismissal': date(2025, 6, 30), 'company_id': self.company.id})
        order.write({'name': 'З-2025/0001'})
        order.action_confirm()

        order.action_cancel()

        self.first_version.invalidate_recordset()
        stale.invalidate_recordset()
        self.assertFalse(self.first_version.contract_date_end,
                         'the employment this order ended reopens')
        self.assertEqual(stale.contract_date_end, date(2024, 12, 31),
                         'the older employment keeps its own end date')

    def test_legacy_number_copied_onto_a_later_employment_is_refused(self):
        """Creating a version copies the termination number onto the new
        employment. Cancelling the old order then has a later contract in the
        way, and the order says so rather than letting core answer with
        overlapping dates."""
        order = self._dismiss(date(2025, 6, 30))
        self._hire(date(2025, 7, 1))
        later = self._versions() - self.first_version
        later.sudo().write({'termination_order_number': order.name})

        with self.assertRaises(UserError) as caught:
            order.action_cancel()

        self.assertIn('2025-07-01', str(caught.exception))
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30))

    def test_hiring_order_ignores_an_archived_version_on_its_date(self):
        """An archived version is invisible to the contract checks and to the
        unique index, so filling it in would leave the employee with no
        contract for that period and an order that looks saved."""
        self._dismiss(date(2025, 6, 30))
        archived = self.employee.sudo().create_version({
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
        })
        archived.sudo().write({'active': False})

        order = self._hire(date(2025, 7, 1))

        archived.invalidate_recordset()
        self.assertFalse(archived.hire_order_number,
                         'the archived version is left alone')
        live = self.employee.version_ids.filtered(
            lambda v: v.hire_order_number == order.name)
        self.assertEqual(len(live), 1, 'the order opened a live contract')
        self.assertEqual(live.contract_date_start, date(2025, 7, 1))
        self.assertEqual(self.employee.hire_date, date(2025, 1, 1))

    def test_dismissal_records_the_order_without_a_contract_period(self):
        """Cards carried over from other systems can have no contract dates at
        all. There is no period to close — core rejects an end date without a
        start — but the dismissal order still has to be traceable."""
        employee = self.env['hr.employee'].create({
            'name': 'ТЕСТ Без періоду', 'company_id': self.company.id})
        order = self.env['hr.order'].create({
            'order_type': 'dismissal', 'subject': 'Звільнення',
            'employee_id': employee.id, 'date': date(2025, 6, 30),
            'date_dismissal': date(2025, 6, 30), 'company_id': self.company.id})

        order.action_confirm()

        versions = employee.with_context(active_test=False).version_ids
        self.assertTrue(versions)
        for version in versions:
            self.assertEqual(version.termination_order_number, order.name)
            self.assertEqual(version.termination_order_date, order.date)
            self.assertFalse(version.contract_date_end,
                             'no period on record, nothing to close')
        # Core keeps no departure for an employee without a contract (it
        # refuses one), so there is nothing to hold a departure date; the
        # card is archived all the same.
        self.assertFalse(order.departure_id)
        self.assertFalse(employee.active)

    def test_editing_a_past_hiring_order_keeps_the_contract_closed(self):
        """The sync runs on every write touching the order's job, dates or
        number — including a correction made to the order of an employee who
        has since left. It must not reopen the period the dismissal closed."""
        self._dismiss(date(2025, 6, 30))
        hire_order = self.env['hr.order'].search([
            ('employee_id', '=', self.employee.id),
            ('order_type', '=', 'hiring')], limit=1)
        if not hire_order:
            hire_order = self._hire(date(2025, 1, 1))
            self.first_version.invalidate_recordset()

        hire_order.write({'job_id': self.job.id})

        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30),
                         'the dismissal, not the hiring order, owns the end date')
        self.assertEqual(self.first_version.job_id, self.job)

    def test_editing_a_past_hiring_order_with_several_versions(self):
        """Same correction on a contract seen through several versions: the
        sibling versions carry the same period, so they are the same contract
        and must not be reported as one standing in the way."""
        self.employee.sudo().create_version({
            'date_version': date(2025, 3, 1),
            'contract_date_start': date(2025, 1, 1),
        })
        hire_order = self._hire(date(2025, 1, 1))
        self._dismiss(date(2025, 6, 30))

        hire_order.write({'job_id': self.job.id})

        versions = self._versions().filtered(
            lambda v: v.contract_date_start == date(2025, 1, 1))
        self.assertEqual(len(versions), 2)
        self.assertEqual(set(versions.mapped('contract_date_end')),
                         {date(2025, 6, 30)})

    def test_fixed_term_rehire_keeps_its_own_end_date(self):
        """A version prepared by hand for a re-hire inherits the termination
        order number of the employment before it — core's create_version
        copies the field. That number alone must not be taken for this
        period's closure, or the order would leave the fixed-term contract it
        opens without an end date."""
        self._dismiss(date(2025, 6, 30))
        prepared = self.employee.sudo().create_version({
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
        })
        self.assertTrue(prepared.termination_order_number,
                        'core copies the number of the previous dismissal')

        order = self._hire(date(2025, 7, 1))
        order.write({'is_fixed_term': True, 'date_end': date(2025, 12, 31)})

        prepared.invalidate_recordset()
        self.assertEqual(prepared.contract_date_end, date(2025, 12, 31),
                         'the order sets the end date of its own contract')
        self.first_version.invalidate_recordset()
        self.assertEqual(self.first_version.contract_date_end, date(2025, 6, 30),
                         'the previous period stays as the dismissal closed it')
