import re
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# monobank payment states (GET /ext/v1/payment/{id}/state).
MONO_STATE_MAP = {
    'DRAFT': 'draft',
    'DECLINED': 'declined',
    'IN_STATEMENT': 'in_statement',
}
IBAN_UA_RE = re.compile(r'^UA\d{27}$')
PAY_CODE_RE = re.compile(r'^\d{3}$')


def _clean(value):
    return (value or '').replace(' ', '').upper()


class L10nUaBankPaymentLine(models.Model):
    _inherit = 'l10n_ua.bank.payment.line'

    # Budget payments (taxes, fees): the bank needs the payment code and the
    # additional information, and the purpose follows their format.
    mono_pay_code = fields.Char(
        string='Payment Code', size=3,
        help='Budget payments only: three-digit code of the payment type '
             '(e.g. 101), as the State Treasury expects it.')
    mono_additional_info = fields.Char(
        string='Additional Info',
        help='Budget payments only: additional information of the payment, '
             '6 to 130 characters.')
    mono_ultimate_debit_name = fields.Char(
        string='Actual Payer',
        help='Budget payments only: name of the actual payer, when the tax '
             'is paid for someone else.')
    mono_ultimate_debit_code = fields.Char(
        string='Actual Payer Code',
        help='EDRPOU, RNOKPP or document number of the actual payer.')

    mono_payment_id = fields.Char(
        string='monobank Payment ID', readonly=True, copy=False, index=True)
    mono_external_ref = fields.Char(
        string='External Reference', readonly=True, copy=False, index=True,
        help='Reference the payment was prepared with; the bank statement '
             'line of the executed payment carries it too.')
    mono_idempotency_key = fields.Char(
        string='Idempotency Key', readonly=True, copy=False)
    mono_state = fields.Selection([
        ('draft', 'Awaiting signature'),
        ('declined', 'Declined'),
        ('in_statement', 'In statement'),
        ('error', 'Error'),
    ], string='monobank State', readonly=True, copy=False)
    mono_error = fields.Text(string='monobank Error', readonly=True, copy=False)
    mono_statement_line_id = fields.Many2one(
        'account.bank.statement.line', string='Statement Line',
        readonly=True, copy=False, index='btree_not_null')

    def _mono_is_budget(self):
        self.ensure_one()
        return bool(self.mono_pay_code)

    def _mono_destination(self):
        """Purpose of the payment. A budget one is built in the format the
        bank documents: `{payCode} {additionalInfo} ЄДРПОУ {own EDRPOU}`."""
        self.ensure_one()
        if self._mono_is_budget():
            return '%s %s ЄДРПОУ %s' % (
                self.mono_pay_code, (self.mono_additional_info or '').strip(),
                self.payment_id._company_edrpou())
        return (self.purpose or '').strip()

    def _mono_check(self):
        """Raise on what the bank would reject, before anything is sent."""
        self.ensure_one()
        name = self.recipient_name or ''
        if not IBAN_UA_RE.match(_clean(self.recipient_iban)):
            raise UserError(_(
                'Recipient IBAN of "%s" is not a Ukrainian IBAN (UA and 27 '
                'digits).', name))
        if not (self.recipient_edrpou or '').strip():
            raise UserError(_(
                'monobank needs the EDRPOU or RNOKPP of the recipient "%s".',
                name))
        if self.mono_pay_code or self.mono_additional_info:
            if not PAY_CODE_RE.match(self.mono_pay_code or ''):
                raise UserError(_(
                    'Payment code of "%s" must be three digits.', name))
            if not 6 <= len((self.mono_additional_info or '').strip()) <= 130:
                raise UserError(_(
                    'Additional info of the budget payment "%s" must be 6 to '
                    '130 characters.', name))
            if not self.payment_id._company_edrpou():
                raise UserError(_(
                    'Set the company EDRPOU: the purpose of a budget payment '
                    'contains it.'))
        if bool(self.mono_ultimate_debit_name) != bool(self.mono_ultimate_debit_code):
            raise UserError(_(
                'Fill in both the name and the code of the actual payer of '
                '"%s", or neither.', name))
        if self.mono_ultimate_debit_name and not (
                3 <= len(self.mono_ultimate_debit_name) <= 240):
            raise UserError(_(
                'Name of the actual payer of "%s" must be 3 to 240 '
                'characters.', name))
        destination = self._mono_destination()
        if not 6 <= len(destination) <= 420:
            raise UserError(_(
                'Payment purpose of "%s" must be 6 to 420 characters.', name))

    def _mono_payload(self, sender_iban):
        self.ensure_one()
        payload = {
            'senderIban': sender_iban,
            'receiver': {
                'iban': _clean(self.recipient_iban),
                'edrpou': (self.recipient_edrpou or '').strip(),
                'name': (self.recipient_name or '').strip(),
            },
            'destination': self._mono_destination(),
            # In kopecks; the bank takes hryvnia only.
            'amount': int(round(self.amount * 100)),
            'currency': '980',
            'externalReference': self.mono_external_ref,
        }
        if self._mono_is_budget():
            payload['payCode'] = self.mono_pay_code
            payload['additionalInfo'] = self.mono_additional_info.strip()
            if self.mono_ultimate_debit_name:
                payload['ultimateDebit'] = {
                    'id': self.mono_ultimate_debit_code.strip(),
                    'name': self.mono_ultimate_debit_name.strip(),
                }
        return payload

    def _mono_keys(self, payload):
        """(external reference, idempotency key) of the line.

        The reference identifies the line in this database. The key is
        derived from the reference and the payment itself, so sending the
        same payment again (after a timeout, or a crash after the bank
        accepted it) cannot create a second one in the bank, while a payment
        corrected after a rejection goes as a new one.
        """
        self.ensure_one()
        dbuuid = self.env['ir.config_parameter'].sudo().get_param(
            'database.uuid') or self.env.cr.dbname
        ref = self.mono_external_ref or 'odoo-%s-bpl-%s' % (dbuuid[:8], self.id)
        body = dict(payload, externalReference=ref)
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, '%s/%s/%r' % (
            dbuuid, ref, sorted(
                (k, repr(v)) for k, v in body.items()))))
        return ref, key

    def _mono_send(self, config, sender_iban):
        """Prepare the payment in monobank. Errors of the bank are kept on
        the line rather than raised: payments prepared before it in the same
        order stay recorded."""
        self.ensure_one()
        ref, key = self._mono_keys(self._mono_payload(sender_iban))
        self.write({'mono_external_ref': ref, 'mono_idempotency_key': key})
        payload = self._mono_payload(sender_iban)
        try:
            result = config._mono_corp_request(
                '/ext/v1/payment/prepare', method='POST', payload=payload,
                idempotency_key=key)
        except UserError as e:
            self.write({'mono_state': 'error', 'mono_error': str(e)})
            return False
        payment_id = (result or {}).get('id') if isinstance(result, dict) else None
        if not payment_id:
            self.write({'mono_state': 'error',
                        'mono_error': _('monobank returned no payment ID: %s', result)})
            return False
        self.write({
            'mono_payment_id': payment_id,
            'mono_state': 'draft',
            'mono_error': False,
            'purpose': payload['destination'],
        })
        return True

    def _mono_refresh(self, config):
        """Read the state of the prepared payment from the bank."""
        for line in self.filtered('mono_payment_id'):
            result = config._mono_corp_request(
                '/ext/v1/payment/%s/state' % line.mono_payment_id)
            state = MONO_STATE_MAP.get((result or {}).get('state'))
            if state and state != line.mono_state:
                line.mono_state = state
        self.filtered(
            lambda l: l.mono_state == 'in_statement'
            and not l.mono_statement_line_id)._mono_link_statement()

    def _mono_link_statement(self):
        """Link executed payments to their bank statement lines."""
        refs = self.filtered('mono_external_ref').mapped('mono_external_ref')
        if not refs:
            return
        st_lines = self.env['account.bank.statement.line'].sudo().search([
            ('l10n_ua_mono_external_ref', 'in', refs)])
        self._mono_match_statement_lines(st_lines, self)

    @api.model
    def _mono_match_statement_lines(self, st_lines, lines=None):
        """Link statement lines to the payment lines with their reference."""
        by_ref = {}
        for st_line in st_lines:
            by_ref.setdefault(st_line.l10n_ua_mono_external_ref, st_line)
        if lines is None:
            lines = self.search([
                ('mono_external_ref', 'in', list(by_ref)),
                ('mono_statement_line_id', '=', False)])
        for line in lines:
            st_line = by_ref.get(line.mono_external_ref)
            if st_line and line.payment_id.company_id == st_line.company_id:
                line.write({
                    'mono_statement_line_id': st_line.id,
                    # Booked in the statement: executed, whatever the last
                    # state read was.
                    'mono_state': 'in_statement',
                })

    def write(self, vals):
        frozen = set(vals) & {
            'recipient_name', 'recipient_edrpou', 'recipient_iban', 'amount',
            'mono_pay_code', 'mono_additional_info',
            'mono_ultimate_debit_name', 'mono_ultimate_debit_code'}
        if frozen and self.filtered('mono_payment_id'):
            raise UserError(_(
                'The payment is already prepared in monobank and cannot be '
                'changed here. Decline it in monobank and add a new line.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_mono_prepared(self):
        if self.filtered(lambda l: l.mono_payment_id and l.mono_state != 'declined'):
            raise UserError(_(
                'The payment is already prepared in monobank. Decline it there '
                'first.'))
