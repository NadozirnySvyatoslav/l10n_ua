import logging
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
    termination_reason_id = fields.Many2one(
        'hr.termination.reason',
        string='Termination Reason (from catalog)',
        tracking=True,
        help='Pick a structured termination reason from the legal catalog. '
             'When set, the dismissal order will use its full_text and render '
             'description_html (legal explanation) in the print template.',
    )

    # Vacation-specific fields
    vacation_date_from = fields.Date(string='Vacation Start Date', tracking=True)
    vacation_date_to = fields.Date(string='Vacation End Date', tracking=True)
    leave_id = fields.Many2one(
        'hr.leave',
        string='Leave Record',
        ondelete='set null',
        copy=False,
        index=True,
    )
    # Related field — eliminates duplication (рек. №5)
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Leave Type',
        related='leave_id.holiday_status_id',
        store=True,
        readonly=False,   # writable for orders being created standalone before leave is linked
        precompute=True,
        tracking=True,
    )

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

    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                order_type = vals.get('order_type', 'other')
                sequence_code = f'hr.order.{order_type}'
                vals['name'] = self.env['ir.sequence'].next_by_code(sequence_code) or 'New'

        # Collect indices of vacation orders that need a leave auto-created
        leave_vals_list = []
        leave_indices = []
        for idx, vals in enumerate(vals_list):
            if (vals.get('order_type') == 'vacation'
                    and not vals.get('leave_id')
                    and not self.env.context.get('_creating_order_from_leave')):
                leave_vals_list.append({
                    'employee_id': vals.get('employee_id'),
                    'holiday_status_id': vals.get('holiday_status_id'),
                    'request_date_from': vals.get('vacation_date_from'),
                    'request_date_to': vals.get('vacation_date_to'),
                })
                leave_indices.append(idx)

        if leave_vals_list:
            leaves = self.env['hr.leave'].with_context(
                _creating_leave_from_order=True
            ).create(leave_vals_list)
            for idx, leave in zip(leave_indices, leaves):
                vals_list[idx]['leave_id'] = leave.id

        # Add _sync_order_leave context to prevent duplicate orders on inverse related fields write
        orders = super(HrOrder, self.with_context(_sync_order_leave=True)).create(vals_list)

        # Back-link leaves → orders in a single write per leave
        for order in orders:
            if order.leave_id and not order.leave_id.order_id:
                order.leave_id.with_context(_sync_order_leave=True).write(
                    {'order_id': order.id}
                )
        orders._sync_hiring_to_employee()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('_sync_order_leave'):
            if {'vacation_date_from', 'vacation_date_to'} & vals.keys():
                for order in self.filtered(
                    lambda o: o.order_type == 'vacation' 
                    and o.leave_id
                    and o.leave_id.state not in ('validate', 'validate1')
                ):
                    order.leave_id.with_context(_sync_order_leave=True).write({
                        'date_from': fields.Datetime.from_string(str(order.vacation_date_from)) if order.vacation_date_from else False,
                        'date_to': fields.Datetime.from_string(str(order.vacation_date_to)) if order.vacation_date_to else False,
                    })
        if vals.keys() & {'order_type', 'employee_id', 'job_id', 'date', 'date_start', 'date_end', 'is_fixed_term', 'name'}:    
            self._sync_hiring_to_employee()

        return result

    def _sync_failure(self, exc):
        """Convert a sync exception into a UserError so it surfaces as a modal
        dialog the user must dismiss before continuing. Overlapping-contract
        failures get a tailored, actionable message."""
        text = str(exc)
        if 'contract running' in text or 'active versions' in text \
                or 'overlap' in text.lower():
            return UserError(_(
                "Cannot update the employee contract: this employee already "
                "has an active contract during the selected period.\n\n"
                "Please either:\n"
                "- Change the start date so that it does not overlap with the "
                "existing contract, or\n"
                "- Create a new employee if this employee should have multiple "
                "active contracts."
            ))
        return UserError(_(
            "Failed to sync hiring order data to the employee record.\n\n"
            "Details: %s",
            text,
        ))

    def _sync_hiring_to_employee(self):
        """Sync hiring order data to the employee record.

        Three writes happen, each guarded by its own savepoint so a failure in
        one does not abort the order transaction or the other writes:

        1. Employee-level fields (``job_id``, ``hire_date``).
        2. Current version metadata (``hire_order_number``, ``hire_order_date``,
           ``job_id``) — so the employee form immediately reflects the latest
           order; these fields do not interact with contract period overlap
           checks.
        3. A dedicated contract version covering the order's period
           (``contract_date_start``/``contract_date_end``) — created or updated
           in place, matched first by ``hire_order_number`` and then by
           ``date_version``.
        """
        Version = self.env['hr.version']
        for order in self.filtered(lambda o: o.order_type == 'hiring' and o.employee_id):
            order_no = order.name if order.name and order.name != 'New' else False

            # 1. Employee-level fields
            emp_vals = {}
            if order.job_id:
                emp_vals['job_id'] = order.job_id.id
            hire_date_val = order.date_start or order.date
            if hire_date_val:
                emp_vals['hire_date'] = hire_date_val
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

            # 2. Current version metadata (visible on the employee form)
            current = order.employee_id.current_version_id
            if current:
                current_vals = {}
                if order_no:
                    current_vals['hire_order_number'] = order_no
                if order.date:
                    current_vals['hire_order_date'] = order.date
                if order.job_id:
                    current_vals['job_id'] = order.job_id.id
                if current_vals:
                    try:
                        with self.env.cr.savepoint():
                            current.sudo().write(current_vals)
                    except _SYNC_EXC as exc:
                        _logger.warning(
                            "Hiring order %s: cannot sync metadata to current version of %s: %s",
                            order.name, order.employee_id.display_name, exc,
                        )
                        raise self._sync_failure(exc) from exc

            # 3. Contract version for the new employment period
            version_start = order.date_start or order.date
            if not version_start:
                continue

            version_vals = {
                'contract_date_start': order.date_start or False,
                'hire_order_date': order.date or False,
            }
            if order_no:
                version_vals['hire_order_number'] = order_no
            if order.job_id:
                version_vals['job_id'] = order.job_id.id
            if order.is_fixed_term:
                version_vals['contract_date_end'] = order.date_end or False
            else:
                version_vals['contract_date_end'] = False

            existing = Version.browse()
            if order_no:
                existing = Version.search([
                    ('employee_id', '=', order.employee_id.id),
                    ('hire_order_number', '=', order_no),
                ], limit=1)
            if not existing:
                existing = Version.search([
                    ('employee_id', '=', order.employee_id.id),
                    ('date_version', '=', version_start),
                ], limit=1)

            try:
                with self.env.cr.savepoint():
                    if existing:
                        version_vals['date_version'] = version_start
                        existing.sudo().write(version_vals)
                    else:
                        version_vals['date_version'] = version_start
                        version_vals['employee_id'] = order.employee_id.id
                        template = order.employee_id.current_version_id
                        if template:
                            template.sudo().copy(version_vals)
                        else:
                            version_vals.setdefault('company_id', order.company_id.id)
                            Version.sudo().create(version_vals)
            except _SYNC_EXC as exc:
                _logger.warning(
                    "Hiring order %s: cannot sync to contract version of %s: %s",
                    order.name, order.employee_id.display_name, exc,
                )
                raise self._sync_failure(exc) from exc

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        for order in self.filtered(lambda o: o.leave_id):
            order.leave_id.message_post(
                body=_('Linked vacation order %s was cancelled. Leave state is unchanged.', order.name)
            )
        return True

    def unlink(self):
        leaves = self.mapped('leave_id')
        res = super().unlink()
        for leave in leaves.exists():
            leave.message_post(body=_('Linked vacation order was deleted.'))
        return res

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
