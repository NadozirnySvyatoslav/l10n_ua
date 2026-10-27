from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaEdoSendWizard(models.TransientModel):
    _name = 'l10n_ua.edo.send.wizard'
    _description = 'Send a Document to EDO'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    company_id = fields.Many2one('res.company', compute='_compute_defaults_from_record')
    account_id = fields.Many2one(
        'l10n_ua.edo.account', string='EDO Account', required=True,
        domain="[('company_id', '=', company_id), ('provider', '!=', False)]")
    report_model = fields.Char(compute='_compute_defaults_from_record')
    report_id = fields.Many2one(
        'ir.actions.report', string='Document', required=True,
        domain="[('model', '=', report_model), ('report_type', '=', 'qweb-pdf')]")
    title = fields.Char(required=True)
    recipient_edrpou = fields.Char(string='Recipient ЄДРПОУ')
    recipient_emails = fields.Char(
        string='Recipient E-mails', help='Comma-separated; used when the recipient is not in the service yet.')
    send_now = fields.Boolean(
        string='Recipient Signs First', default=False,
        help='Off: the document is uploaded and waits for your signature in the service, '
             'where you sign and send it. On: it goes to the recipient right away, '
             'who signs it first.')

    def _record(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id)

    @api.depends('res_model', 'res_id')
    def _compute_defaults_from_record(self):
        for wizard in self:
            record = wizard._record() if wizard.res_model and wizard.res_id else None
            wizard.report_model = wizard.res_model
            company = record['company_id'] if record and 'company_id' in record._fields else False
            wizard.company_id = company or self.env.company

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
        reports = record._edo_reports()
        partner = record._edo_partner()
        meta = record._edo_meta()
        vals.update({
            'account_id': account.id or False,
            'report_id': reports[:1].id or False,
            'title': meta.get('title') or record.display_name,
            'recipient_edrpou': partner['edrpou'] if partner and 'edrpou' in partner._fields else False,
            'recipient_emails': partner.email if partner else False,
        })
        return vals

    def action_send(self):
        self.ensure_one()
        record = self._record()
        if not record.exists():
            raise UserError(_('The document no longer exists.'))
        emails = [e.strip() for e in (self.recipient_emails or '').split(',') if e.strip()]
        doc = record._edo_send(
            self.account_id, self.report_id, self.recipient_edrpou, emails,
            title=self.title, send=self.send_now)
        return {
            'type': 'ir.actions.act_window', 'res_model': doc._name,
            'res_id': doc.id, 'view_mode': 'form', 'target': 'current',
        }
