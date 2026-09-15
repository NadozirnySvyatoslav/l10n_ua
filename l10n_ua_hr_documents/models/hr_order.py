import logging
import math
from datetime import date, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from psycopg2 import IntegrityError

_SYNC_EXC = (UserError, ValidationError, IntegrityError)
_logger = logging.getLogger(__name__)

class HrOrder(models.Model):
    _name = 'hr.order'
    _description = 'HR Order'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Number', readonly=True, copy=False, default='New')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    order_type = fields.Selection([
        ('hiring', 'Hiring'),
        ('dismissal', 'Dismissal'),
        ('transfer', 'Transfer'),
        ('vacation', 'Vacation'),
        ('bonus', 'Bonus'),
        ('sick_leave', 'Sick Leave'),
        ('business_trip', 'Business Trip'),
        ('other', 'Other'),
    ], string='Order Type', required=True, default='other', tracking=True)

    employee_id = fields.Many2one('hr.employee', string='Employee', tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', tracking=True)
    job_id = fields.Many2one('hr.job', string='Job Position', tracking=True)

    # Hiring-specific fields
    date_start = fields.Date(
        string='Employment Start Date',
        tracking=True,
        help='Date when employment begins'
    )
    date_end = fields.Date(
        string='Employment End Date',
        tracking=True,
        help='Contract end date (for fixed-term contracts)'
    )
    is_fixed_term = fields.Boolean(
        string='Fixed-term Contract',
        help='Check if this is a fixed-term (строковий) contract'
    )
    employment_form = fields.Selection([
        ('main', 'Main place of work'),
        ('secondary', 'Concurrent employment'),
    ], string='Employment Type', tracking=True)

    # Dismissal-specific fields
    date_dismissal = fields.Date(
        string='Dismissal Date',
        tracking=True,
        help='Effective date of employment termination'
    )
    dismissal_reason = fields.Text(
        string='Dismissal Reason',
        help='Legal basis for dismissal (e.g., "за власним бажанням, ст. 38 КЗпП України")'
    )
    previous_departure_date = fields.Date(
        string='Previous Departure Date (backup)',
        copy=False,
        readonly=True,
        help='Internal: saves employee.departure_date before this dismissal '
             'order was applied, so cancellation can restore it.',
    )
    previous_departure_date_saved = fields.Boolean(
        copy=False,
        readonly=True,
        default=False,
        help='Internal: True if previous_departure_date holds a backed-up value '
             '(needed because False is a legitimate previous value).',
    )
    termination_reason_id = fields.Many2one(
        'hr.termination.reason',
        string='Termination Reason (from catalog)',
        tracking=True,
        help='Pick a structured termination reason from the legal catalog. '
             'When set, the dismissal order will use its full_text and render '
             'description_html (legal explanation) in the print template.',
    )
    include_vacation_compensation = fields.Boolean(
        string='Compensate Unused Vacation',
        default=True,
        help='Add the standard "виплатити компенсацію за N календарних днів '
             'невикористаної відпустки" phrase to the dismissal order.',
    )
    unused_vacation_days = fields.Float(
        string='Unused Vacation Days',
        compute='_compute_unused_vacation_days',
        store=True,
        readonly=False,
        help='Calendar days of unused vacation to compensate on dismissal. '
             'Auto-filled from the vacation balance; editable.',
    )

    @api.depends('order_type', 'employee_id', 'date_dismissal', 'date')
    def _compute_unused_vacation_days(self):
        has_balance = 'hr.vacation.balance' in self.env
        for order in self:
            days = 0.0
            if (has_balance and order.order_type == 'dismissal'
                    and order.employee_id):
                ref_date = (order.date_dismissal or order.date
                            or fields.Date.context_today(order))
                balances = self.env['hr.vacation.balance'].search([
                    ('employee_id', '=', order.employee_id.id),
                    ('year', '=', ref_date.year),
                ])
                days = sum(balances.mapped('remaining_days'))
            order.unused_vacation_days = max(0.0, days)

    def unused_vacation_days_phrase(self):
        """«N календарних днів» для наказу: ціле число з узгодженим іменником.

        Дробові дні округлюються вгору, на користь працівника (роз'яснення
        Мінсоцполітики), і одним округленням і для умови друку, і для числа.
        Порожній рядок, коли компенсувати нічого.
        """
        self.ensure_one()
        # Допуск на похибку float: 12.000000001 — це 12, а не 13.
        days = math.ceil(round(self.unused_vacation_days, 6))
        if days <= 0:
            return ''
        if days % 10 == 1 and days % 100 != 11:
            noun = 'календарний день'
        elif 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
            noun = 'календарні дні'
        else:
            noun = 'календарних днів'
        return f'{days} {noun}'

    is_locked = fields.Boolean(
        string='Locked by a Linked Document',
        compute='_compute_is_locked',
        help='Technical: true when another document already holds the same '
             'data as this order, so the fields the two must agree on are '
             'locked here. Nothing locks an order on its own; a module that '
             'links orders to another record (Ukraine - HR Holidays ties a '
             'vacation order to its time off) redefines the computation.',
    )

    def _compute_is_locked(self):
        # No linked document exists at this level, so nothing is ever locked.
        # A module adding such a link overrides this method and declares its
        # own @api.depends on the link field.
        self.is_locked = False

    # Vacation-specific fields
    vacation_date_from = fields.Date(string='Vacation Start Date', tracking=True)
    vacation_date_to = fields.Date(string='Vacation End Date', tracking=True)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Auto-fill department and job position from employee."""
        if self.employee_id:
            self.department_id = self.employee_id.department_id
            self.job_id = self.employee_id.job_id

    @api.onchange('termination_reason_id')
    def _onchange_termination_reason_id(self):
        """Auto-fill dismissal_reason text from the picked catalog entry."""
        if self.termination_reason_id and self.termination_reason_id.full_text:
            self.dismissal_reason = self.termination_reason_id.full_text

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Reset cross-company employee/department/job when company changes."""
        if self.employee_id and self.employee_id.company_id \
                and self.employee_id.company_id != self.company_id:
            self.employee_id = False
        if self.department_id and self.department_id.company_id \
                and self.department_id.company_id != self.company_id:
            self.department_id = False
        if self.job_id and self.job_id.company_id \
                and self.job_id.company_id != self.company_id:
            self.job_id = False

    subject = fields.Char(string='Subject', required=True, tracking=True, compute='_compute_subject', store=True, readonly=False, precompute=True)



    ORDER_TYPE_SUBJECTS = {
        'hiring': 'Про прийняття на роботу',
        'dismissal': 'Про припинення трудового договору',
        'transfer': 'Про переведення на іншу роботу',
        'vacation': 'Про надання відпустки',
        'bonus': 'Про преміювання',
        'sick_leave': 'Про оплату листка непрацездатності',
        'business_trip': 'Про направлення у службове відрядження',
        'other': 'Наказ',
    }

    @api.depends('order_type')
    def _compute_subject(self):
        for order in self:
            if not order.subject:
                order.subject = self.ORDER_TYPE_SUBJECTS.get(order.order_type, 'Наказ')

    content = fields.Html(string='Content')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    confirmed_by_id = fields.Many2one(
        'res.users',
        string='Confirmed By',
        readonly=True,
        copy=False,
        help='User who confirmed this order in the system — the HR officer '
             'recording that the printed order was signed. Kept as the audit '
             'trail of the act the order performs (e.g. granting a leave).',
    )
    confirmed_date = fields.Datetime(
        string='Confirmed On',
        readonly=True,
        copy=False,
        help='When the order was confirmed in the system.',
    )

    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                  default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                order_type = vals.get('order_type', 'other')
                sequence_code = f'hr.order.{order_type}'
                vals['name'] = self.env['ir.sequence'].next_by_code(sequence_code) or 'New'

        orders = super().create(vals_list)
        orders._sync_hiring_to_employee()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if vals.keys() & {'order_type', 'employee_id', 'job_id', 'date', 'date_start', 'date_end', 'is_fixed_term', 'name'}:
            self._sync_hiring_to_employee()

        return result

    def _sync_failure(self, exc):
        """Convert a sync exception into a UserError so it surfaces as a modal
        dialog the user must dismiss before continuing.

        The one refusal users actually run into — an overlapping contract
        period — is raised by :meth:`_check_hiring_period_free` before any
        write is attempted, with the dates spelled out. Recognising it here
        instead is not possible: core raises its messages already translated,
        so matching their English wording never fires in a Ukrainian database.
        """
        return UserError(_(
            "Failed to sync hiring order data to the employee record.\n\n"
            "Details: %s",
            exc,
        ))

    def _sync_hiring_to_employee(self):
        """Sync hiring order data to the employee record.

        Two writes happen, each guarded by its own savepoint so a failure in
        one does not abort the order transaction or the other write:

        1. Employee-level fields (``job_id``).
        2. The contract version the order documents: its period
           (``contract_date_start`` / ``contract_date_end``), the order
           metadata (``hire_order_number``, ``hire_order_date``) and
           ``job_id`` — see :meth:`_find_hiring_version`.

        The order never writes ``hire_date`` on the employee: that field is
        computed from the contract versions, so step 2 is what sets it. An
        order without an explicit ``date_start`` falls back to the order date
        for the contract period, which keeps the version — not the employee
        record — the single source of the hire date.

        The metadata is deliberately NOT stamped on
        ``employee.current_version_id``. That is the version in force today,
        which for a hiring starting tomorrow is still the PREVIOUS
        employment: stamping this order's number on it made the lookup below
        take that old version for the order's own and move it onto the new
        period, erasing the previous contract from the employee's history.
        """
        for order in self.filtered(lambda o: o.order_type == 'hiring' and o.employee_id):
            order_no = order.name if order.name and order.name != 'New' else False

            # 1. Employee-level fields
            emp_vals = {}
            if order.job_id:
                emp_vals['job_id'] = order.job_id.id
            if emp_vals:
                try:
                    with self.env.cr.savepoint():
                        order.employee_id.write(emp_vals)
                except _SYNC_EXC as exc:
                    _logger.warning(
                        "Hiring order %s: cannot sync to employee %s: %s",
                        order.name, order.employee_id.display_name, exc,
                    )
                    raise self._sync_failure(exc) from exc

            # 2. Contract version for the employment period.
            # The period starts on date_start, or on the order date when the
            # order does not spell it out — an employment order always opens a
            # period, and leaving contract_date_start empty would keep the
            # version out of the employee's hire date and out of the core
            # overlap checks.
            version_start = order.date_start or order.date
            if not version_start:
                continue

            version_vals = {
                'date_version': version_start,
                'contract_date_start': version_start,
                'hire_order_date': order.date or False,
            }
            if order_no:
                version_vals['hire_order_number'] = order_no
            if order.job_id:
                version_vals['job_id'] = order.job_id.id

            # Resolved before the savepoint: an overlapping period is reported
            # with its own message, which _sync_failure would otherwise
            # flatten into a bare "failed to sync".
            version = order._find_hiring_version(version_start)

            # A period already closed by a dismissal order is left alone. The
            # sync runs on every write that touches the order's job, dates or
            # number, so editing a long-past hiring order of an employee who
            # has since left would otherwise reopen their contract: the card
            # kept departure_date and the termination order number while the
            # contract ran again, and the employee slipped into every report
            # filtering on `contract_date_end = False`. The dismissal order is
            # what ends a period; only cancelling it may reopen one.
            #
            # The end date has to fall on or after the start of the period the
            # order documents for it to be this period's closure. A version
            # prepared by hand for a re-hire inherits the termination number of
            # the employment before it (core's create_version copies the
            # field), so the number alone would also hold back the end date of
            # a fixed-term re-hire and leave the contract open-ended.
            closed = (version.contract_date_end
                      and version.termination_order_number
                      and version.contract_date_end >= version_start)
            if closed:
                version_end = version.contract_date_end
            else:
                version_end = (
                    (order.date_end or False) if order.is_fixed_term else False)
                version_vals['contract_date_end'] = version_end

            order._check_hiring_period_free(
                version_start, version_end, version)
            try:
                with self.env.cr.savepoint():
                    if not version:
                        version = order._create_hiring_version(version_start)
                    version.sudo().write(version_vals)
            except _SYNC_EXC as exc:
                _logger.warning(
                    "Hiring order %s: cannot sync to contract version of %s: %s",
                    order.name, order.employee_id.display_name, exc,
                )
                raise self._sync_failure(exc) from exc

            # The employee card reads the version in force today, and core
            # refreshes that only once a day (the "HR Employee: Update Current
            # Version" cron). Without this the card keeps showing the previous
            # employment right after the order is issued, and the next order
            # would resolve against that stale value.
            order.employee_id.sudo()._compute_current_version_id()

    def _find_hiring_version(self, version_start):
        """The contract version this order documents, when it already exists.

        Two candidates, in this order:

        1. The version effective on ``version_start`` — typically the contract
           the user prepared by hand before issuing the order. It is the one
           the order documents, and filling it in is also what keeps a second
           version off that date, which the database forbids outright.
        2. The version already carrying this order's number, as long as no
           version sits on that date yet. Moving it is how a corrected start
           date on the order follows through to the contract.

        When both exist and differ, the second one is not this order's any
        more, so its number is cleared: leaving it there would let a later
        sync take that version for the order's own and move it — the mistake
        that erased the previous contract of re-hired employees.

        Archived versions are out of scope on purpose. They are invisible to
        the contract checks and to the unique index on the effective date, so
        writing the order into one leaves the employee with no contract at all
        for that period — the order would look saved and change nothing.

        Returns an empty recordset when the order needs a new version.
        """
        self.ensure_one()
        order_no = self.name if self.name and self.name != 'New' else False
        # Elevated for the same reason core is in hr.version._check_dates:
        # contract dates are manager-level fields, while issuing orders is the
        # job of HR officers, who need not hold that right.
        versions = self.employee_id.sudo().version_ids
        on_date = versions.filtered(
            lambda v: v.date_version == version_start)[:1]
        by_order = versions.filtered(
            lambda v: order_no and v.hire_order_number == order_no)
        if on_date:
            stale = by_order - on_date
            if stale:
                stale.write({
                    'hire_order_number': False,
                    'hire_order_date': False,
                })
            return on_date
        return by_order[:1]

    def _create_hiring_version(self, version_start):
        """A new contract version opening the employment on ``version_start``.

        Core's ``create_version`` is what copies the version in force on that
        date and keeps the contract dates of sibling versions in step; the
        plain create is only the fallback for an employee left with no
        version at all.
        """
        self.ensure_one()
        employee = self.employee_id
        if employee.sudo().version_ids:
            return employee.sudo().create_version({
                'date_version': version_start,
                'contract_date_start': version_start,
                'contract_date_end': False,
            })
        return self.env['hr.version'].sudo().create({
            'employee_id': employee.id,
            'company_id': self.company_id.id,
            'date_version': version_start,
            'contract_date_start': version_start,
        })

    def _check_hiring_period_free(self, version_start, version_end, own_version):
        """Refuse a hiring order whose period overlaps a contract in place.

        Core refuses it as well, from ``hr.version._check_dates``, but only
        once the write is under way and with a message that names no dates
        and arrives already translated — this module cannot tell it apart
        from any other failure, so the user was left with a bare "failed to
        sync". Checking here lets the order name the contract standing in the
        way and say what to do about it.

        The rule mirrors core: two periods that are exactly equal are one
        contract seen through several versions and never conflict, and a
        period with no end date runs to the end of time.
        """
        self.ensure_one()
        end = version_end or date.max
        conflicts = self.employee_id.sudo().version_ids.filtered(
            lambda v: (
                v != own_version
                and v.contract_date_start
                and not (v.contract_date_start == version_start
                         and (v.contract_date_end or date.max) == end)
                and v.contract_date_start <= end
                and version_start <= (v.contract_date_end or date.max)
            )
        )
        if not conflicts:
            return
        conflict = conflicts[0]
        if conflict.contract_date_end:
            raise UserError(_(
                "Cannot start a contract for %(employee)s on %(start)s: the "
                "contract of %(other_start)s - %(other_end)s is still running "
                "that day.\n\n"
                "An employee who leaves and is hired again is free from the "
                "day after the previous contract ends, so hire them from "
                "%(next_day)s.\n\n"
                "If instead the two contracts are meant to run side by side "
                "(concurrent employment next to a job that carries on), "
                "create a separate employee record for it: one record holds "
                "one contract at a time.",
                employee=self.employee_id.display_name,
                start=version_start,
                other_start=conflict.contract_date_start,
                other_end=conflict.contract_date_end,
                next_day=conflict.contract_date_end + timedelta(days=1),
            ))
        raise UserError(_(
            "Cannot start a contract for %(employee)s on %(start)s: the "
            "contract opened on %(other_start)s is still running and carries "
            "no end date.\n\n"
            "Close it first — confirm the dismissal order, or fill in its end "
            "date — and hire the employee from the day after. If the two "
            "contracts are meant to run side by side (concurrent employment), "
            "create a separate employee record for it.",
            employee=self.employee_id.display_name,
            start=version_start,
            other_start=conflict.contract_date_start,
        ))

    def _check_vacation_confirm_rights(self):
        """Confirming a vacation order records that the printed, signed order
        was issued — the legal act that obliges the employee to take the leave,
        and which locks the leave against being refused afterwards.

        HR officers prepare and confirm orders (the director signs the printed
        document), hence the Ukraine HR Officer group: plain HR users, who may
        only maintain employee data, cannot issue one."""
        if self.env.su:
            return
        if self.env.user.has_group('l10n_ua_hr_base.group_hr_ua_officer'):
            return
        raise UserError(_(
            'Confirming a vacation order grants the leave, which requires the '
            '"Ukraine HR: Officer" access rights. Ask an HR officer to confirm '
            'this order.'))

    def action_confirm(self):
        if self.filtered(lambda o: o.order_type == 'vacation'):
            self._check_vacation_confirm_rights()
        self.write({
            'state': 'confirmed',
            'confirmed_by_id': self.env.user.id,
            'confirmed_date': fields.Datetime.now(),
        })
        for order in self.filtered(lambda o: o.order_type == 'dismissal' and o.employee_id):
            order._apply_dismissal()
        # Nothing else is touched: an order moves only through its own
        # buttons, and so does any document linked to it.

    def _current_contract_versions(self):
        """The versions of the employment in force — the latest contract period.

        A contract is a set of versions sharing one ``contract_date_start``;
        the latest of those periods is the employment the employee is living
        now, whether it still runs or has just been closed. Earlier periods
        are previous employments, and core refuses to write contract dates
        across two of them in one go ("Cannot modify multiple versions
        contract dates with different contracts at once") — which is exactly
        what a second dismissal of a re-hired employee used to attempt.

        Versions with no start date carry no period at all and are left out:
        core rejects an end date without a start at database level.

        Contract dates are manager-level fields, so the selection reads them
        elevated the way core does; the records come back in the caller's own
        environment, leaving the write under the user's own rights.
        """
        self.ensure_one()
        versions = self.employee_id.sudo().with_context(
            active_test=False).version_ids.filtered('contract_date_start')
        if not versions:
            return versions.sudo(False)
        latest_start = max(versions.mapped('contract_date_start'))
        return versions.filtered(
            lambda v: v.contract_date_start == latest_start).sudo(False)

    def _apply_dismissal(self):
        """Apply a confirmed dismissal order to the employee:
        close the current contract and archive the employee.

        We write contract_date_end to every version of that contract: Odoo
        core syncs contract_date_end across versions only on
        `create_version`, not on direct `write`, so its other versions would
        keep `contract_date_end = False` and slip through the report filter
        `('contract_date_end', '=', False)`.

        Only the current employment is closed — see
        :meth:`_current_contract_versions`. An earlier contract of a re-hired
        employee keeps the end date of its own dismissal, which is both its
        history and what core requires.
        """
        self.ensure_one()
        employee = self.employee_id
        dismissal_date = self.date_dismissal or self.date
        order_vals = {
            'termination_order_number': self.name,
            'termination_order_date': self.date,
        }
        versions = self._current_contract_versions()
        if versions:
            versions.write({'contract_date_end': dismissal_date, **order_vals})
        else:
            # No contract period on record — nothing to close, and core
            # rejects an end date without a start anyway. The order itself
            # still has to be traceable on the card, so its reference goes in
            # on its own.
            employee.version_ids.write(order_vals)
        # Back up the previous value once per apply/revert cycle so revert
        # restores exactly what was there before this order — independent of
        # later manual edits.
        if not self.previous_departure_date_saved:
            self.write({
                'previous_departure_date': employee.departure_date or False,
                'previous_departure_date_saved': True,
            })
        employee.departure_date = dismissal_date
        if employee.active:
            employee.active = False

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        for order in self.filtered(lambda o: o.order_type == 'dismissal' and o.employee_id):
            order._revert_dismissal()
        return True

    def _revert_dismissal(self):
        """Revert the effects of a previously confirmed dismissal order.

        We reopen exactly what this order closed: its number AND the end date
        it wrote. The number alone is not enough — creating a version copies
        it over to the new employment, so a later period can carry the number
        of the dismissal that ended the previous one, and reverting by number
        would reopen a period this order never touched (and fail, since the
        two belong to different contracts).

        Matching on both cannot pick up two employments at once: periods
        sharing an end date necessarily overlap, and core allows no such pair
        on one employee. Cards written by the old code, which stamped the
        number on every version, therefore resolve to the one employment that
        really ended on that date.
        """
        self.ensure_one()
        employee = self.employee_id
        dismissal_date = self.date_dismissal or self.date
        versions = employee.sudo().with_context(
            active_test=False).version_ids.filtered(
            lambda v: v.termination_order_number == self.name
            and v.contract_date_end == dismissal_date
        ).sudo(False)
        later_start = min(
            (v.contract_date_start
             for v in employee.sudo().with_context(active_test=False).version_ids
             if v.contract_date_start and v.contract_date_start > dismissal_date),
            default=False)
        if versions and later_start:
            # Reopening this period would leave it running for ever, on top of
            # the employment that has already started — core refuses that, and
            # its message speaks of overlapping dates rather than of the order
            # the user is trying to cancel.
            raise UserError(_(
                "Cannot cancel the dismissal of %(employee)s: a new contract "
                "for this employee already starts on %(start)s.\n\n"
                "Reopening the contract this order closed would put the "
                "employee under two contracts at once. Correct or delete the "
                "later contract first, then cancel this order.",
                employee=employee.display_name,
                start=later_start,
            ))
        if versions:
            versions.write({
                'contract_date_end': False,
                'termination_order_number': False,
                'termination_order_date': False,
            })
        if self.previous_departure_date_saved:
            employee.with_context(active_test=False).departure_date = \
                self.previous_departure_date or False
            self.write({
                'previous_departure_date': False,
                'previous_departure_date_saved': False,
            })
        if not employee.active:
            employee.with_context(active_test=False).active = True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_load_template(self):
        self.ensure_one()
        return {
            'name': 'Select Template',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.order.template.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id, 'default_order_type': self.order_type},
        }
