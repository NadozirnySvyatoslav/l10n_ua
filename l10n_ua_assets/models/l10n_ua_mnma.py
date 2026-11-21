"""Low-value non-current tangible assets (МНМА) management."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaMnma(models.Model):
    _name = 'l10n_ua.mnma'
    _description = 'МНМА (малоцінні необоротні матеріальні активи)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Найменування',
        required=True,
        tracking=True,
    )
    inventory_number = fields.Char(
        string='Інвентарний номер',
        tracking=True,
    )
    date = fields.Date(
        string='Дата придбання',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    document_date = fields.Date(
        string='Дата документа',
        default=fields.Date.context_today,
        copy=False,
        help='Дата акту введення в експлуатацію або списання, що оформлюється '
             'наступним. Порожнє — сьогоднішня дата. Після операції поле '
             'очищується для наступного документа.',
    )
    commission_date = fields.Date(
        string='Дата введення',
        tracking=True,
    )
    commission_act_number = fields.Char(
        string='№ акту введення',
        copy=False,
    )
    writeoff_date = fields.Date(
        string='Дата списання',
        tracking=True,
    )
    writeoff_act_number = fields.Char(
        string='№ акту списання',
        copy=False,
    )
    writeoff_reason = fields.Text(
        string='Причина списання',
    )
    original_value = fields.Monetary(
        string='Первісна вартість',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    write_off_method = fields.Selection(
        selection=[
            ('50_50', '50/50 (50% при введенні, 50% при списанні)'),
            ('100', '100% при введенні в експлуатацію'),
        ],
        string='Метод списання',
        default='50_50',
        required=True,
        tracking=True,
    )
    depreciation_value = fields.Monetary(
        string='Знос',
        compute='_compute_depreciation',
        store=True,
        currency_field='currency_id',
    )
    residual_value = fields.Monetary(
        string='Залишкова вартість',
        compute='_compute_depreciation',
        store=True,
        currency_field='currency_id',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('in_use', 'В експлуатації'),
            ('written_off', 'Списано'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )
    responsible_id = fields.Many2one(
        'res.users',
        string='Відповідальний',
        default=lambda self: self.env.user,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Підрозділ',
    )
    location = fields.Char(
        string='Місцезнаходження',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    notes = fields.Text(
        string='Примітки',
    )

    @api.depends('original_value', 'write_off_method', 'state')
    def _compute_depreciation(self):
        for record in self:
            if record.state == 'draft':
                record.depreciation_value = 0
                record.residual_value = record.original_value
            elif record.state == 'in_use':
                if record.write_off_method == '100':
                    record.depreciation_value = record.original_value
                    record.residual_value = 0
                else:
                    record.depreciation_value = record.original_value / 2
                    record.residual_value = record.original_value / 2
            else:
                record.depreciation_value = record.original_value
                record.residual_value = 0

    def _operation_date(self):
        """Date of the act being issued: document date, or today."""
        self.ensure_one()
        return self.document_date or fields.Date.context_today(self)

    def action_commission(self):
        """Put MNMA into operation."""
        for rec in self:
            vals = {
                'state': 'in_use',
                'commission_date': rec._operation_date(),
                'document_date': False,
            }
            if not rec.commission_act_number:
                vals['commission_act_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.mnma.commission.act'
                ) or _('New')
            rec.write(vals)

    def action_write_off(self):
        """Write off MNMA."""
        for rec in self:
            writeoff_date = rec._operation_date()
            if rec.commission_date and writeoff_date < rec.commission_date:
                raise UserError(_(
                    'Дата списання МНМА "%(name)s" (%(writeoff)s) не може бути '
                    'раніше дати введення в експлуатацію (%(commission)s).',
                    name=rec.display_name, writeoff=writeoff_date,
                    commission=rec.commission_date))
            vals = {
                'state': 'written_off',
                'writeoff_date': writeoff_date,
                'document_date': False,
            }
            if not rec.writeoff_act_number:
                vals['writeoff_act_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.mnma.writeoff.act'
                ) or _('New')
            rec.write(vals)

    def action_draft(self):
        self.write({
            'state': 'draft',
            'commission_date': False,
            'commission_act_number': False,
            'writeoff_date': False,
            'writeoff_act_number': False,
            'writeoff_reason': False,
        })

    # --- Print actions ---

    def action_print_commission_act(self):
        """Print MNMA Commissioning Act."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_mnma_commission'
        ).report_action(self)

    def action_print_writeoff_act(self):
        """Print MNMA Write-off Act."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_mnma_writeoff'
        ).report_action(self)
