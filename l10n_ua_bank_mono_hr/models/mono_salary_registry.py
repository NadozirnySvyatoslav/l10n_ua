import hashlib
import json
import logging
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# The v2 registry API takes up to 1000 recipients per batch, 100 000 in all.
MONO_REGISTRY_BATCH = 1000
MONO_REGISTRY_MAX = 100000

# Bank status (GET /ext/v1/payments/salary/registries/{id}/status) → state.
# The specification lists FAILED and SUCCEEDED; the description of the
# endpoint FAIL and PAYMENTS_DONE: both spellings are accepted.
MONO_REGISTRY_STATUS = {
    'SAVED': 'saved',
    'IN_PROGRESS': 'in_progress',
    'PREPARED': 'prepared',
    'CHANGE_REQUIRED': 'change_required',
    'FAILED': 'failed',
    'FAIL': 'failed',
    'SUCCEEDED': 'succeeded',
    'PAYMENTS_DONE': 'succeeded',
}
MONO_REGISTRY_FINAL = ('failed', 'succeeded')


class L10nUaMonoSalaryRegistryType(models.Model):
    _name = 'l10n_ua.mono.salary.registry.type'
    _description = 'monobank Salary Registry Type'
    _order = 'config_id, name'

    config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='monobank Connection',
        required=True, ondelete='cascade')
    alias = fields.Char(required=True)
    name = fields.Char(string='Description', required=True)
    additional_purpose_allowed = fields.Boolean(
        string='Per-recipient Purpose',
        help='The bank accepts an addition to the purpose for each recipient.')
    active = fields.Boolean(default=True)

    _config_alias_uniq = models.Constraint(
        'UNIQUE(config_id, alias)',
        'A registry type is listed once per connection.',
    )

    @api.model
    def _mono_fetch(self, config):
        """Refresh the registry types of a connection from the bank."""
        types = config._mono_corp_request('/ext/v1/payments/salary/registries/types')
        if not isinstance(types, list):
            raise UserError(_("monobank API error: %s") % types)
        existing = self.with_context(active_test=False).search(
            [('config_id', '=', config.id)])
        by_alias = {t.alias: t for t in existing}
        seen = self.browse()
        for item in types:
            alias = item.get('alias')
            if not alias:
                continue
            vals = {
                'name': item.get('description') or alias,
                'additional_purpose_allowed': bool(item.get('additionalPurposeAllowed')),
                'active': True,
            }
            record = by_alias.get(alias)
            if record:
                record.write(vals)
            else:
                record = self.create(dict(vals, config_id=config.id, alias=alias))
            seen |= record
        (existing - seen).write({'active': False})
        return seen


class L10nUaMonoSalaryRegistry(models.Model):
    """Salary registry sent to monobank through the Corporate API.

    Recipients go in batches of up to 1000 under one registry reference
    (`POST /ext/v2/payments/salary/registries`), then the registry is
    finalized; the director signs it in monobank. Its status is then polled.
    """
    _name = 'l10n_ua.mono.salary.registry'
    _description = 'monobank Salary Registry'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Registry Name', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='monobank Connection', required=True,
        domain="[('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),"
               " ('company_id', '=', company_id)]")
    registry_type_id = fields.Many2one(
        'l10n_ua.mono.salary.registry.type', string='Registry Type',
        domain="[('config_id', '=', config_id)]",
        help='Type of payment in monobank (salary, advance, …). Fetch the '
             'list from the bank with the button.')
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Payslip Batch')
    line_ids = fields.One2many(
        'l10n_ua.mono.salary.registry.line', 'registry_id', string='Recipients')
    line_count = fields.Integer(compute='_compute_totals', store=True)
    total_amount = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    registry_reference = fields.Char(readonly=True, copy=False, index=True)
    bank_registry_id = fields.Char(
        string='monobank Registry ID', readonly=True, copy=False)
    batches_sent = fields.Integer(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('loading', 'Loading'),
        ('finalized', 'Submitted'),
        ('saved', 'Saved'),
        ('in_progress', 'In progress'),
        ('prepared', 'Prepared'),
        ('change_required', 'Change required'),
        ('failed', 'Failed'),
        ('succeeded', 'Paid'),
    ], default='draft', required=True, tracking=True, copy=False)
    decline_reason = fields.Text(readonly=True, copy=False)
    status_updated_at = fields.Datetime(readonly=True, copy=False)

    @api.depends('line_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    def _mono_reference(self):
        self.ensure_one()
        if not self.registry_reference:
            dbuuid = self.env['ir.config_parameter'].sudo().get_param(
                'database.uuid') or self.env.cr.dbname
            self.registry_reference = 'odoo-%s-sr-%s' % (dbuuid[:8], self.id)
        return self.registry_reference

    def action_fetch_types(self):
        self.ensure_one()
        types = self.env['l10n_ua.mono.salary.registry.type']._mono_fetch(self.config_id)
        if not self.registry_type_id and types:
            self.registry_type_id = types[:1]
        return True

    def action_sync_contacts(self):
        self.ensure_one()
        employees = self.line_ids.mapped('employee_id')
        if not employees:
            raise UserError(_('The registry has no employees.'))
        report = employees._l10n_ua_mono_sync_contacts(self.config_id)
        self.message_post(body=employees._l10n_ua_mono_contacts_report(report))
        return True

    def _check_ready(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Add at least one recipient.'))
        if len(self.line_ids) > MONO_REGISTRY_MAX:
            raise UserError(_('monobank takes at most %d recipients in one registry.')
                            % MONO_REGISTRY_MAX)
        if not self.registry_type_id:
            raise UserError(_('Choose the registry type (fetch the list from monobank).'))
        if self.date_from > self.date_to:
            raise UserError(_('The period starts after it ends.'))
        config = self.config_id
        if (config.journal_id.currency_id or config.company_id.currency_id).name != 'UAH':
            raise UserError(_('monobank pays salaries in UAH only.'))
        self.config_id._mono_corp_iban()
        allowed = self.registry_type_id.additional_purpose_allowed
        for line in self.line_ids:
            line._check_ready(allowed)

    def _batch_payload(self, lines):
        self.ensure_one()
        payload = {
            'registryReference': self._mono_reference(),
            'registryName': self.name,
            'senderIban': self.config_id._mono_corp_iban(),
            'salaryRegistryType': self.registry_type_id.alias,
            'from': self.date_from.isoformat(),
            'to': self.date_to.isoformat(),
            'recipients': [line._recipient() for line in lines],
        }
        return payload

    @staticmethod
    def _idempotency_key(payload, index):
        """Same batch, same key: a batch sent again after a timeout is not
        added twice."""
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return str(uuid.uuid5(uuid.NAMESPACE_URL, '%s/%d/%s' % (
            payload['registryReference'], index, digest)))

    def action_send(self):
        """Send the recipients in batches and finalize the registry.

        A failed batch stops the sending without losing what went before:
        the next attempt goes on from the batch that failed.
        """
        self.ensure_one()
        if self.state not in ('draft', 'loading'):
            raise UserError(_('The registry is already submitted to monobank.'))
        self._check_ready()
        lines = self.line_ids.sorted('id')
        batches = [lines[i:i + MONO_REGISTRY_BATCH]
                   for i in range(0, len(lines), MONO_REGISTRY_BATCH)]
        error = None
        for index in range(self.batches_sent, len(batches)):
            payload = self._batch_payload(batches[index])
            try:
                result = self.config_id._mono_corp_request(
                    '/ext/v2/payments/salary/registries', method='POST',
                    payload=payload,
                    idempotency_key=self._idempotency_key(payload, index))
            except UserError as e:
                error = str(e)
                break
            vals = {'batches_sent': index + 1, 'state': 'loading'}
            if isinstance(result, dict) and result.get('id'):
                vals['bank_registry_id'] = result['id']
            self.write(vals)
        if error is None:
            try:
                self.config_id._mono_corp_request(
                    '/ext/v2/payments/salary/registries/finalize', method='POST',
                    payload={'registryReference': self._mono_reference()})
            except UserError as e:
                error = str(e)
            else:
                self.write({'state': 'finalized',
                            'status_updated_at': fields.Datetime.now()})
        if error:
            body = _('monobank rejected the registry after %(sent)d of %(total)d '
                     'batch(es): %(error)s',
                     sent=self.batches_sent, total=len(batches), error=error)
        else:
            body = _('Registry submitted to monobank: %(count)d recipient(s), '
                     '%(total).2f UAH. It waits for the signature in monobank.',
                     count=self.line_count, total=self.total_amount)
        self.message_post(body=body)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('monobank'),
                'message': body,
                'type': 'warning' if error else 'success',
                'sticky': bool(error),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_refresh_status(self):
        for rec in self:
            if not rec.bank_registry_id:
                raise UserError(_('The registry has no monobank ID yet.'))
            result = rec.config_id._mono_corp_request(
                '/ext/v1/payments/salary/registries/%s/status' % rec.bank_registry_id) or {}
            state = MONO_REGISTRY_STATUS.get(result.get('status'))
            reason = result.get('declineReason') or False
            vals = {'status_updated_at': fields.Datetime.now()}
            if state and state != rec.state:
                vals['state'] = state
            if reason != (rec.decline_reason or False):
                vals['decline_reason'] = reason
            rec.write(vals)
            if reason and 'decline_reason' in vals:
                rec.message_post(body=_('monobank: %s', reason))
        return True

    @api.model
    def _cron_refresh_status(self):
        registries = self.search([
            ('bank_registry_id', '!=', False),
            ('state', 'not in', ('draft', 'loading') + MONO_REGISTRY_FINAL),
        ])
        for registry in registries:
            try:
                with self.env.cr.savepoint():
                    registry.action_refresh_status()
            except UserError as e:
                _logger.warning("monobank: status of registry %s: %s", registry.id, e)

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('A registry sent to monobank cannot be deleted.'))
        return super().unlink()


class L10nUaMonoSalaryRegistryLine(models.Model):
    _name = 'l10n_ua.mono.salary.registry.line'
    _description = 'monobank Salary Registry Recipient'
    _order = 'registry_id, id'

    registry_id = fields.Many2one(
        'l10n_ua.mono.salary.registry', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    payslip_id = fields.Many2one('hr.payslip', string='Payslip')
    full_name = fields.Char(string='Full Name', required=True)
    inn = fields.Char(string='RNOKPP')
    document_type = fields.Selection([
        ('OLD_PASSPORT', 'Passport (old format)'),
        ('ID_CARD', 'ID card'),
        ('FOREIGN_PASSPORT', 'Foreign passport'),
    ], string='Document')
    document_series = fields.Char(string='Series')
    document_number = fields.Char(string='Document No.')
    iban = fields.Char(string='IBAN', required=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    additional_purpose = fields.Char(
        string='Purpose Addition',
        help='Appended to the registry purpose as is, without a separator: '
             'start it with a space when needed.')
    currency_id = fields.Many2one(related='registry_id.currency_id')

    def _check_ready(self, additional_purpose_allowed):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Amount of %s must be positive.', self.full_name))
        if not (self.inn or (self.document_type and self.document_number)):
            raise UserError(_('%s has neither an RNOKPP nor a document.', self.full_name))
        if self.additional_purpose and not additional_purpose_allowed:
            raise UserError(_(
                'The registry type %(type)s takes no purpose addition (%(name)s).',
                type=self.registry_id.registry_type_id.name, name=self.full_name))

    def _recipient(self):
        self.ensure_one()
        vals = {
            'fullName': self.full_name,
            'iban': (self.iban or '').replace(' ', '').upper(),
            'amount': int(round(self.amount * 100)),
        }
        if self.inn:
            vals['inn'] = self.inn
        else:
            vals['documentType'] = self.document_type
            vals['documentNumber'] = self.document_number
            if self.document_series:
                vals['documentSeries'] = self.document_series
        if self.additional_purpose:
            vals['additionalPurpose'] = self.additional_purpose
        return vals

    @api.model
    def _vals_from_employee(self, employee, amount, payslip=None):
        identity = employee._l10n_ua_mono_identity()
        return {
            'employee_id': employee.id,
            'payslip_id': payslip.id if payslip else False,
            'full_name': employee.name,
            'inn': identity.get('inn') or False,
            'document_type': identity.get('documentType') or False,
            'document_number': identity.get('documentNumber') or False,
            'document_series': identity.get('documentSeries') or False,
            'iban': employee._l10n_ua_mono_iban(),
            'amount': amount,
        }
