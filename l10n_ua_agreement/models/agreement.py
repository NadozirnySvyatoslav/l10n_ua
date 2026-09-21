import base64

from odoo import _, api, fields, models


class Agreement(models.Model):
    _inherit = 'agreement'

    # --- Українізація міток базових полів OCA-модуля agreement ---
    code = fields.Char(string='Номер договору')
    name = fields.Char(string='Назва договору')
    partner_id = fields.Many2one(string='Клієнт')
    agreement_type_id = fields.Many2one(string='Тип договору')
    is_template = fields.Boolean(string='Шаблон')
    signature_date = fields.Date(string='Дата підпису')
    start_date = fields.Date(string='Дата початку')
    end_date = fields.Date(string='Дата завершення')
    domain = fields.Selection(
        selection=[('sale', 'Продаж'), ('purchase', 'Закупівля')],
        string='Сфера',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('to_sign', 'На підписанні'),
            ('signed', 'Підписаний'),
            ('expired', 'Завершений'),
            ('cancelled', 'Скасований'),
        ],
        string='Стан',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    parent_agreement_id = fields.Many2one(
        'agreement',
        string='Основний договір',
        ondelete='cascade',
        copy=False,
        help='Заповнюється для додаткових угод — посилання на основний договір.',
    )
    child_agreement_ids = fields.One2many(
        'agreement',
        'parent_agreement_id',
        string='Додаткові угоди',
    )
    child_agreement_count = fields.Integer(
        compute='_compute_child_agreement_count',
    )
    is_amendment = fields.Boolean(
        string='Додаткова угода',
        compute='_compute_is_amendment',
        store=True,
    )
    subject = fields.Html(
        string='Предмет договору',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Валюта',
        default=lambda self: self.env.company.currency_id,
    )
    amount_total = fields.Monetary(
        string='Сума договору',
        currency_field='currency_id',
    )
    signed_document = fields.Binary(
        string='Підписаний документ',
        copy=False,
        attachment=True,
    )
    signed_filename = fields.Char(
        string="Ім'я файлу",
        copy=False,
    )
    sign_request_count = fields.Integer(
        compute='_compute_sign_request_count',
        string='Запити на підпис',
    )
    contract_ids = fields.One2many(
        'contract.contract',
        'agreement_id',
        string='Періодичні договори',
    )
    contract_count = fields.Integer(
        compute='_compute_contract_count',
    )

    # ------------------------------------------------------------------
    # Меню
    # ------------------------------------------------------------------
    @api.model
    def _l10n_ua_deactivate_legacy_type_menus(self):
        """Приховати меню «Типи договорів» зі старих знімків OCA/agreement.

        XML-id цього меню в OCA/agreement@19.0 змінювався між знімками
        (``agreement_type_menu_main`` / ``agreement_type_menu`` → ``agreement_type``),
        а в поточному його немає взагалі. Ми оголошуємо власний menuitem під
        «Налаштуваннями», тож будь-яке успадковане меню OCA дало б дубль у
        оновленій БД. Відсутність id — нормальний випадок (чиста інсталяція),
        тому резолвимо толерантно.
        """
        for xmlid in (
            'agreement.agreement_type_menu_main',
            'agreement.agreement_type_menu',
            'agreement.agreement_type',
        ):
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu._name == 'ir.ui.menu':
                menu.active = False

    @api.depends('parent_agreement_id')
    def _compute_is_amendment(self):
        for rec in self:
            rec.is_amendment = bool(rec.parent_agreement_id)

    @api.depends('child_agreement_ids')
    def _compute_child_agreement_count(self):
        for rec in self:
            rec.child_agreement_count = len(rec.child_agreement_ids)

    @api.depends('contract_ids')
    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = len(rec.contract_ids)

    def _compute_sign_request_count(self):
        SignRequest = self.env['sign.oca.request']
        for rec in self:
            rec.sign_request_count = SignRequest.search_count(
                [('record_ref', '=', '%s,%s' % (rec._name, rec.id))]
            ) if rec.id else 0

    # ------------------------------------------------------------------
    # Дії стану
    # ------------------------------------------------------------------
    def action_confirm(self):
        self.write({'state': 'to_sign'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    # ------------------------------------------------------------------
    # Підпис через sign_oca
    # ------------------------------------------------------------------
    def action_request_signature(self):
        self.ensure_one()
        pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
            'l10n_ua_agreement.action_report_agreement', res_ids=self.ids
        )
        request = self.env['sign.oca.request'].create({
            'name': _('Договір %s') % (self.code or self.name),
            'data': base64.b64encode(pdf_content).decode(),
            'filename': '%s.pdf' % (self.code or 'agreement'),
            'record_ref': '%s,%s' % (self._name, self.id),
        })
        if self.state == 'draft':
            self.state = 'to_sign'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Запит на підпис'),
            'res_model': 'sign.oca.request',
            'res_id': request.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_act(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_agreement.action_report_agreement_act'
        ).report_action(self)

    def action_view_sign_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Запити на підпис'),
            'res_model': 'sign.oca.request',
            'view_mode': 'list,form',
            'domain': [('record_ref', '=', '%s,%s' % (self._name, self.id))],
        }

    # ------------------------------------------------------------------
    # Додаткові угоди
    # ------------------------------------------------------------------
    def action_add_amendment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Додаткова угода'),
            'res_model': 'agreement',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_parent_agreement_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_agreement_type_id': self.agreement_type_id.id,
            },
        }

    def action_view_child_agreements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Додаткові угоди'),
            'res_model': 'agreement',
            'view_mode': 'list,form',
            'domain': [('parent_agreement_id', '=', self.id)],
            'context': {
                'default_parent_agreement_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }

    # ------------------------------------------------------------------
    # Періодичні рахунки (contract)
    # ------------------------------------------------------------------
    def action_create_contract(self):
        self.ensure_one()
        contract = self.env['contract.contract'].create({
            'name': self.name,
            'partner_id': self.partner_id.id,
            'agreement_id': self.id,
            'contract_type': 'sale',
            'company_id': self.company_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Періодичний договір'),
            'res_model': 'contract.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Періодичні договори'),
            'res_model': 'contract.contract',
            'view_mode': 'list,form',
            'domain': [('agreement_id', '=', self.id)],
            'context': {'default_agreement_id': self.id},
        }
