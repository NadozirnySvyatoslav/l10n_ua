import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# How long a prepared payment is watched by the scheduled refresh.
MONO_REFRESH_DAYS = 45


def _clean(value):
    return (value or '').replace(' ', '').upper()


class L10nUaBankPayment(models.Model):
    _inherit = 'l10n_ua.bank.payment'

    transfer_method = fields.Selection([
        ('file', 'File signed with КЕП'),
        ('mono_api', 'monobank API (signed in the monobank app)'),
    ], string='Transfer Method', default='file', required=True, tracking=True,
        help='File: the payment file is signed with a qualified signature and '
             'uploaded to the client-bank. monobank API: each payment is '
             'prepared in monobank and signed there by the director, in the '
             'app or the web cabinet; no signature in Odoo is needed.')
    mono_config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='monobank Connection',
        compute='_compute_mono_config_id', store=True, readonly=False,
        domain="[('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),"
               " ('company_id', '=', company_id)]",
        help='Corporate API connection of the payer account. Found by the '
             'payer IBAN.')
    mono_status = fields.Selection([
        ('pending', 'Awaiting signature'),
        ('partial', 'Partially executed'),
        ('done', 'Executed'),
        ('declined', 'Declined'),
        ('error', 'Error'),
    ], string='monobank Status', compute='_compute_mono_status', store=True,
        tracking=True)
    mono_unsent = fields.Boolean(
        string='Has Unsent Payments', compute='_compute_mono_unsent')

    @api.depends('payer_account_id', 'transfer_method', 'company_id')
    def _compute_mono_config_id(self):
        Config = self.env['l10n_ua.bank.sync.config']
        for rec in self:
            if rec.transfer_method != 'mono_api' or (
                    rec.mono_config_id and rec.mono_config_id._mono_corp_iban_or_none() \
                    == _clean(rec.payer_account_id.acc_number)):
                rec.mono_config_id = rec.mono_config_id
                continue
            rec.mono_config_id = Config._mono_corp_config_for_iban(
                rec.payer_account_id.acc_number, rec.company_id)

    @api.depends('line_ids.mono_state', 'line_ids.mono_payment_id')
    def _compute_mono_status(self):
        for rec in self:
            states = set(rec.line_ids.mapped('mono_state'))
            if not states - {False}:
                rec.mono_status = False
            elif 'error' in states:
                rec.mono_status = 'error'
            elif 'draft' in states or False in states:
                rec.mono_status = 'pending'
            elif states == {'in_statement'}:
                rec.mono_status = 'done'
            elif states == {'declined'}:
                rec.mono_status = 'declined'
            else:
                rec.mono_status = 'partial'

    @api.depends('transfer_method', 'line_ids.mono_payment_id')
    def _compute_mono_unsent(self):
        for rec in self:
            rec.mono_unsent = rec.transfer_method == 'mono_api' and any(
                not line.mono_payment_id for line in rec.line_ids)

    def write(self, vals):
        protected = set(vals) & {'payer_account_id', 'transfer_method', 'mono_config_id'}
        if protected and any(rec.line_ids.filtered('mono_payment_id') for rec in self):
            raise UserError(_(
                'Payments of this order are already prepared in monobank: the '
                'payer account and the transfer method cannot change.'))
        return super().write(vals)

    def _mono_sender(self):
        """(connection, sender IBAN) of the order, checked."""
        self.ensure_one()
        if self.transfer_method != 'mono_api':
            raise UserError(_('This order is not sent through the monobank API.'))
        iban = _clean(self.payer_account_id.acc_number)
        if not self.mono_config_id:
            raise UserError(_(
                'No monobank corporate API connection for the account %s. '
                'Create one (Bank → Bank Connections) with the journal of '
                'this account.', iban or '-'))
        own = self.mono_config_id._mono_corp_iban_or_none()
        if own and own != iban:
            raise UserError(_(
                'The monobank connection %(config)s reads the account '
                '%(own)s, not the payer account %(iban)s.',
                config=self.mono_config_id.display_name, own=own, iban=iban))
        config = self.mono_config_id
        if (config.journal_id.currency_id or config.company_id.currency_id).name != 'UAH':
            raise UserError(_('monobank API prepares payments in UAH only.'))
        return self.mono_config_id, iban

    def action_mono_send(self):
        """Prepare the payments in monobank; the director signs them in the
        monobank app or web cabinet."""
        self.ensure_one()
        config, iban = self._mono_sender()
        self._check_ready()
        lines = self.line_ids.filtered(lambda l: not l.mono_payment_id)
        if not lines:
            raise UserError(_('All payments of this order are already in monobank.'))
        for line in lines:
            line._mono_check()
        sent = failed = 0
        for line in lines:
            if line._mono_send(config, iban):
                sent += 1
            else:
                failed += 1
        if not self.line_ids.filtered(lambda l: not l.mono_payment_id):
            self.state = 'sent'
        if failed:
            errors = '; '.join(
                '%s: %s' % (l.recipient_name, l.mono_error)
                for l in lines if l.mono_state == 'error')
            body = _('monobank: %(sent)d payment(s) prepared for signing, '
                     '%(failed)d rejected: %(errors)s',
                     sent=sent, failed=failed, errors=errors)
        else:
            body = _('monobank: %d payment(s) prepared and waiting for the '
                     'signature in the monobank app.', sent)
        self.message_post(body=body)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('monobank'),
                'message': body,
                'type': 'warning' if failed else 'success',
                'sticky': bool(failed),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_mono_refresh(self):
        for rec in self:
            config, _iban = rec._mono_sender()
            before = {l.id: l.mono_state for l in rec.line_ids}
            rec.line_ids._mono_refresh(config)
            changed = rec.line_ids.filtered(
                lambda l: before.get(l.id) != l.mono_state)
            if changed:
                states = dict(rec.line_ids._fields[
                    'mono_state']._description_selection(self.env))
                rec.message_post(body=_('monobank: %s', '; '.join(
                    '%s — %s' % (l.recipient_name, states.get(l.mono_state))
                    for l in changed)))
        return True

    @api.model
    def _cron_mono_refresh(self):
        """Refresh the payments awaiting signature or their statement line."""
        since = fields.Datetime.now() - timedelta(days=MONO_REFRESH_DAYS)
        orders = self.search([
            ('transfer_method', '=', 'mono_api'),
            ('mono_status', 'in', ('pending', 'partial', 'done')),
            ('create_date', '>=', since),
        ])
        for order in orders:
            lines = order.line_ids.filtered(
                lambda l: l.mono_payment_id and (
                    l.mono_state == 'draft'
                    or (l.mono_state == 'in_statement' and not l.mono_statement_line_id)))
            if not lines:
                continue
            try:
                with self.env.cr.savepoint():
                    order.action_mono_refresh()
            except UserError as e:
                _logger.warning("monobank: refresh of %s failed: %s", order.name, e)
