import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date

from .agreement_type import DIRECTIONS


class L10nUaAgreement(models.Model):
    _name = 'l10n_ua.agreement'
    _description = 'Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.sign.mixin']
    _order = 'start_date desc, id desc'
    _rec_names_search = ['code', 'name']

    _code_uniq = models.Constraint(
        'UNIQUE(code, commercial_partner_id, company_id)',
        'This agreement number already exists for this partner.',
    )

    code = fields.Char(
        string='Number', required=True, copy=False, tracking=True, index='trigram',
        default='/',
        help='Taken from the agreement sequence when left as "/".',
    )
    name = fields.Char(string='Title', required=True, tracking=True)
    direction = fields.Selection(
        DIRECTIONS, required=True, tracking=True,
        compute='_compute_direction', store=True, readonly=False, precompute=True,
    )
    agreement_type_id = fields.Many2one(
        'l10n_ua.agreement.type', string='Type', tracking=True,
        domain="[('direction', '=', direction)]",
    )
    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True, tracking=True,
        ondelete='restrict', index=True,
    )
    commercial_partner_id = fields.Many2one(
        'res.partner', compute='_compute_commercial_partner_id',
        store=True, precompute=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    user_id = fields.Many2one(
        'res.users', string='Responsible', tracking=True,
        default=lambda self: self.env.user,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('to_sign', 'To Sign'),
            ('signed', 'Signed'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status', required=True, default='draft', tracking=True, copy=False,
    )
    active = fields.Boolean(default=True)
    start_date = fields.Date(
        string='Start Date', tracking=True, default=fields.Date.context_today)
    end_date = fields.Date(
        string='End Date', tracking=True,
        help='Leave empty for an agreement valid until the obligations are fulfilled.',
    )
    signature_date = fields.Date(string='Signature Date', tracking=True, copy=False)
    parent_id = fields.Many2one(
        'l10n_ua.agreement', string='Main Agreement', index=True,
        ondelete='cascade', copy=False,
        help='Set on amendments: the agreement they amend.',
    )
    amendment_ids = fields.One2many('l10n_ua.agreement', 'parent_id', string='Amendments')
    amendment_count = fields.Integer(compute='_compute_amendment_count')
    is_amendment = fields.Boolean(compute='_compute_is_amendment', store=True)
    subject = fields.Html(
        compute='_compute_subject', store=True, readonly=False, precompute=True)
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    amount_total = fields.Monetary(string='Amount', tracking=True)
    note = fields.Html(string='Internal Note')

    # КЕП: підпис нашої сторони (CAdES із вбудованим PDF) і підписаний
    # контрагентом документ (скан або його .p7s).
    kep_signature = fields.Binary(string='Our КЕП Signature', attachment=True, copy=False)
    kep_signature_filename = fields.Char(copy=False)
    kep_signed_by_id = fields.Many2one('res.users', string='Signed by', copy=False, readonly=True)
    kep_signed_on = fields.Datetime(string='Signed on', copy=False, readonly=True)
    signed_document = fields.Binary(
        string='Signed Document', attachment=True, copy=False,
        help='The agreement signed by both parties: a scan or a signed file.',
    )
    signed_filename = fields.Char(copy=False)

    sale_order_ids = fields.One2many('sale.order', 'l10n_ua_agreement_id', string='Sales Orders')
    sale_order_count = fields.Integer(compute='_compute_sale_order_count')

    @api.depends('agreement_type_id')
    def _compute_direction(self):
        for rec in self:
            if rec.agreement_type_id:
                rec.direction = rec.agreement_type_id.direction
            elif not rec.direction:
                rec.direction = rec.parent_id.direction or 'sale'

    @api.depends('partner_id')
    def _compute_commercial_partner_id(self):
        for rec in self:
            rec.commercial_partner_id = rec.partner_id.commercial_partner_id

    @api.depends('agreement_type_id')
    def _compute_subject(self):
        for rec in self:
            if rec.agreement_type_id.subject_template and not rec.subject:
                rec.subject = rec.agreement_type_id.subject_template

    @api.depends('parent_id')
    def _compute_is_amendment(self):
        for rec in self:
            rec.is_amendment = bool(rec.parent_id)

    @api.depends('amendment_ids')
    def _compute_amendment_count(self):
        for rec in self:
            rec.amendment_count = len(rec.amendment_ids)

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = len(rec.sale_order_ids)

    @api.depends('code', 'name', 'start_date')
    def _compute_display_name(self):
        for rec in self:
            label = _('No. %s', rec.code) if rec.code else ''
            if rec.start_date:
                label = _('%(number)s of %(date)s', number=label,
                          date=format_date(self.env, rec.start_date))
            rec.display_name = f'{label} {rec.name or ""}'.strip()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', '/') in ('/', False, ''):
                company = self.env['res.company'].browse(
                    vals.get('company_id')) or self.env.company
                vals['code'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'l10n_ua.agreement', sequence_date=vals.get('start_date')) or '/'
        return super().create(vals_list)

    def copy_data(self, default=None):
        vals_list = super().copy_data(default)
        for rec, vals in zip(self, vals_list):
            vals.setdefault('name', _('%s (copy)', rec.name))
        return vals_list

    # ------------------------------------------------------------------
    # Стани
    # ------------------------------------------------------------------
    def action_to_sign(self):
        self.write({'state': 'to_sign'})

    def action_mark_signed(self):
        for rec in self:
            rec.write({
                'state': 'signed',
                'signature_date': rec.signature_date or fields.Date.context_today(rec),
            })

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    @api.model
    def _cron_expire(self):
        """Підписані договори з минулою датою завершення — у «Завершені»."""
        self.search([
            ('state', '=', 'signed'),
            ('end_date', '!=', False),
            ('end_date', '<', fields.Date.context_today(self)),
        ]).write({'state': 'expired'})

    # ------------------------------------------------------------------
    # КЕП (l10n_ua_sign): підпис нашої сторони в браузері
    # ------------------------------------------------------------------
    def _agreement_pdf(self):
        self.ensure_one()
        pdf, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
            'l10n_ua_agreement.action_report_agreement', res_ids=self.ids)
        return pdf

    def _agreement_filename(self):
        self.ensure_one()
        safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.code or 'agreement')
        return f'{safe}.pdf'

    def action_sign_kep(self):
        self.ensure_one()
        if self.state not in ('draft', 'to_sign'):
            raise UserError(_('Only a draft agreement or one to sign can be signed.'))
        return self.action_kep_sign()

    def kep_prepare_signing(self):
        self.ensure_one()
        return {
            'auth_subject': None,
            'submit_label': _('Sign the agreement'),
            'documents': [{
                'name': 'agreement',
                'data_b64': base64.b64encode(self._agreement_pdf()).decode(),
                'format': 'cades',
                'filename': self._agreement_filename(),
            }],
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        signature = signed.get('agreement')
        if not signature:
            raise UserError(_('No signature was received for the agreement.'))
        filename = f'{self._agreement_filename()}.p7s'
        self.write({
            'kep_signature': signature,
            'kep_signature_filename': filename,
            'kep_signed_by_id': self.env.user.id,
            'kep_signed_on': fields.Datetime.now(),
            'state': 'to_sign' if self.state == 'draft' else self.state,
        })
        self.message_post(
            body=_('Signed with КЕП by %s.', self.env.user.name),
            attachments=[(filename, base64.b64decode(signature))],
        )
        return {'receipt': _('The agreement is signed with КЕП.')}

    # ------------------------------------------------------------------
    # Друк, додаткові угоди, продажі
    # ------------------------------------------------------------------
    def action_print_act(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_agreement.action_report_agreement_act').report_action(self)

    def action_add_amendment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Amendment'),
            'res_model': 'l10n_ua.agreement',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_parent_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_direction': self.direction,
                'default_agreement_type_id': self.agreement_type_id.id,
                'default_currency_id': self.currency_id.id,
                'default_name': self.name,
            },
        }

    def action_view_amendments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Amendments'),
            'res_model': 'l10n_ua.agreement',
            'view_mode': 'list,form',
            'domain': [('parent_id', '=', self.id)],
            'context': {'default_parent_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sale.action_quotations_with_onboarding')
        action.update({
            'domain': [('l10n_ua_agreement_id', '=', self.id)],
            'context': {
                'default_l10n_ua_agreement_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        })
        return action
