from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaEdoSendWizard(models.TransientModel):
    _name = 'l10n_ua.edo.send.wizard'
    _description = 'Send a Document to EDO'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    res_ids = fields.Char(help='Comma-separated ids when several documents are sent.')
    record_count = fields.Integer(compute='_compute_record_count')
    company_id = fields.Many2one('res.company', compute='_compute_defaults_from_record')
    account_id = fields.Many2one(
        'l10n_ua.edo.account', string='EDO Account', required=True,
        domain="[('company_id', '=', company_id), ('provider', '!=', False)]")
    report_model = fields.Char(compute='_compute_defaults_from_record')
    report_id = fields.Many2one(
        'ir.actions.report', string='Document', required=True,
        domain="[('model', '=', report_model), ('report_type', '=', 'qweb-pdf')]")
    category_id = fields.Many2one(
        'l10n_ua.edo.category', string='Category',
        compute='_compute_category_id', store=True, readonly=False,
        domain="[('account_id', '=', account_id)]",
        help='Category in the service; proposed from the categories of printed forms of the account.')
    title = fields.Char(help='Only for a single document; several keep their own titles.')
    recipient_edrpou = fields.Char(string='Recipient ЄДРПОУ')
    recipient_emails = fields.Char(
        string='Recipient E-mails', help='Comma-separated; used when the recipient is not in the service yet.')
    send_now = fields.Boolean(
        string='Recipient Signs First', default=False,
        help='Off: the document is uploaded and waits for your signature: sign it with КЕП here '
             'or in the service, then it is sent. On: it goes to the recipient right away, '
             'who signs it first.')
    sign_now = fields.Boolean(
        string='Sign with КЕП Now', default=True,
        help='Right after the upload, sign the document with КЕП in the browser and send it.')

    def _target_ids(self):
        self.ensure_one()
        ids = [int(i) for i in (self.res_ids or '').split(',') if i.strip()]
        return ids or [self.res_id]

    def _records(self):
        return self.env[self.res_model].browse(self._target_ids())

    def _record(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id)

    @api.depends('res_ids', 'res_id')
    def _compute_record_count(self):
        for wizard in self:
            wizard.record_count = len(wizard._target_ids()) if wizard.res_model else 0

    @api.depends('res_model', 'res_id')
    def _compute_defaults_from_record(self):
        for wizard in self:
            record = wizard._record() if wizard.res_model and wizard.res_id else None
            wizard.report_model = wizard.res_model
            company = record['company_id'] if record and 'company_id' in record._fields else False
            wizard.company_id = company or self.env.company

    @api.depends('account_id', 'report_id')
    def _compute_category_id(self):
        for wizard in self:
            wizard.category_id = wizard.account_id._category_for(wizard.report_id) \
                if wizard.account_id and wizard.report_id else False

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        model, res_id = vals.get('res_model'), vals.get('res_id')
        if not (model and res_id):
            return vals
        record = self.env[model].browse(res_id)
        company = record['company_id'] if 'company_id' in record._fields and record['company_id'] \
            else self.env.company
        account = self.env['l10n_ua.edo.account'].search(
            [('company_id', '=', company.id), ('provider', '!=', False)], limit=1)
        edrpou, emails = record._edo_recipient()
        vals.update({
            'account_id': account.id or False,
            'report_id': record._edo_reports()[:1].id or False,
            'title': record._edo_meta().get('title') or record.display_name,
            'recipient_edrpou': edrpou,
            'recipient_emails': ', '.join(emails) or False,
        })
        return vals

    def action_send(self):
        self.ensure_one()
        records = self._records().exists()
        if not records:
            raise UserError(_('The documents no longer exist.'))
        category = self.category_id.code or None
        if len(records) == 1:
            emails = [e.strip() for e in (self.recipient_emails or '').split(',') if e.strip()]
            doc = records._edo_send(
                self.account_id, self.report_id, self.recipient_edrpou, emails,
                title=self.title, category=category, send=self.send_now)
            if self.sign_now and not self.send_now:
                if not doc.can_sign:
                    doc.action_refresh()
                if doc.can_sign:
                    return doc.action_edo_sign()
            return {
                'type': 'ir.actions.act_window', 'res_model': doc._name,
                'res_id': doc.id, 'view_mode': 'form', 'target': 'current',
            }
        return self._send_many(records, category)

    def _send_many(self, records, category):
        """Each record to its own counterparty; a record that fails is reported
        and does not stop the others."""
        docs = self.env['l10n_ua.edo.document']
        failed = []
        for record in records:
            edrpou, emails = record._edo_recipient()
            try:
                with self.env.cr.savepoint():
                    docs |= record._edo_send(self.account_id, self.report_id, edrpou, emails,
                                             category=category, send=self.send_now)
            except UserError as error:
                failed.append(f'{record.display_name}: {error.args[0]}')
        message = _('Sent to EDO: %(sent)s of %(total)s.', sent=len(docs), total=len(records))
        if failed:
            message += '\n' + '\n'.join(failed)
        action = {
            'type': 'ir.actions.act_window', 'name': _('EDO Documents'),
            'res_model': docs._name, 'view_mode': 'list,form',
            'domain': [('id', 'in', docs.ids)], 'target': 'current',
        }
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('EDO'), 'message': message, 'sticky': bool(failed),
                'type': 'warning' if failed else 'success',
                'next': action if docs else {'type': 'ir.actions.act_window_close'},
            },
        }
