from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrPspApplication(models.Model):
    _name = 'hr.psp.application'
    _description = 'Заява про застосування податкової соціальної пільги'
    _order = 'date_from desc, id desc'

    name = fields.Char(
        string='Номер заяви',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Працівник',
        required=True,
        index=True,
        ondelete='restrict',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    rnokpp = fields.Char(
        related='employee_id.rnokpp',
        string='РНОКПП (ІПН)',
        store=True,
        index=True,
        readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Чернетка'),
        ('active', 'Чинна'),
    ], string='Статус', default='draft', required=True)

    psp_type = fields.Selection([
        ('standard', 'Стандартна (50%)'),
        ('150', '150%'),
        ('200', '200%'),
    ], string='Розмір ПСП', default='standard', required=True)

    date_from = fields.Date(
        string='Дата подання',
        required=True,
        default=fields.Date.context_today,
        help='Дата подання заяви. ПСП застосовується починаючи з місяця цієї дати.'
    )
    date_to = fields.Date(
        string='Дата закінчення',
        help='Дата закінчення / відмови. У місяць цієї дати ПСП уже не нараховується.'
    )
    active = fields.Boolean(string='Активно', default=True)
    note = fields.Text(
        string='Підстава та підтвердні документи',
        help='Підстави для застосування пільги та перелік наданих підтвердних документів.'
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_psp_application_attachment_rel',
        'application_id',
        'attachment_id',
        string='Документи',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.psp.application') or _('New')
        return super().create(vals_list)

    def action_activate(self):
        for app in self:
            app.state = 'active'
        return True

    def action_draft(self):
        for app in self:
            app.state = 'draft'
        return True

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for app in self:
            if app.date_to and app.date_to < app.date_from:
                raise ValidationError(_("Дата закінчення не може бути ранішою за дату подання!"))

    @api.constrains('state', 'employee_id', 'date_from', 'date_to')
    def _check_rnokpp_unique_active_period(self):
        for app in self:
            if app.state != 'active':
                continue
            if not app.rnokpp:
                raise ValidationError(
                    _("Працівник %s не має заповненого РНОКПП (ІПН). "
                      "Заповніть РНОКПП у картці співробітника перед підтвердженням заяви!") %
                    app.employee_id.name
                )

            start_month = app.date_from.replace(day=1)
            # In the month of date_to, PSP no longer applies:
            # effective end month is the month preceding date_to
            if app.date_to:
                end_month = app.date_to.replace(day=1) - relativedelta(days=1)
            else:
                end_month = None

            # Skip checking if application effectively has no active months
            if end_month and end_month < start_month:
                continue

            # Query all active applications with the same RNOKPP across all companies
            domain = [
                ('id', '!=', app.id),
                ('rnokpp', '=', app.rnokpp),
                ('state', '=', 'active'),
            ]
            other_apps = self.env['hr.psp.application'].sudo().search(domain)
            for other in other_apps:
                other_start = other.date_from.replace(day=1)
                if other.date_to:
                    other_end = other.date_to.replace(day=1) - relativedelta(days=1)
                else:
                    other_end = None

                if other_end and other_end < other_start:
                    continue

                overlaps = True
                if end_month and other_start > end_month:
                    overlaps = False
                if other_end and other_end < start_month:
                    overlaps = False

                if overlaps:
                    raise ValidationError(
                        _("Працівник з РНОКПП %s вже має чинну заяву про застосування ПСП %s "
                          "(співробітник: %s, компанія: %s) на цей період! "
                          "Згідно з пп. 169.2.1 ПКУ, ПСП може застосовуватися лише за одним місцем роботи.") %
                        (app.rnokpp, other.name, other.employee_id.name, other.company_id.name)
                    )
