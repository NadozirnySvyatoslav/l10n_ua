from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


AGE_CATEGORY = [
    ('0_5', '0-5 років'),
    ('6_17', '6-17 років'),
    ('18_39', '18-39 років'),
    ('40_64', '40-64 років'),
    ('65+', '65+ років'),
]


class L10nUaMedecinPatient(models.Model):
    """Пацієнт медичного закладу.

    Прив'язується до `res.partner` (фізособа). Може мати активну декларацію
    з лікарем ПМД — це основа для розрахунку капітації НСЗУ.
    """
    _name = 'l10n_ua.medecin.patient'
    _description = 'Пацієнт'
    _order = 'partner_id'
    _rec_name = 'display_name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one(
        'res.partner', string='Фізособа', required=True, ondelete='restrict',
        tracking=True,
        help='Фізична особа — пацієнт. Контактні дані, адреса, ПІБ зберігаються тут.')
    patient_card_no = fields.Char(
        string='Номер мед.картки', index=True, copy=False, tracking=True,
        help='Внутрішній номер амбулаторної картки')
    company_id = fields.Many2one(
        'res.company', string='Заклад', required=True,
        default=lambda self: self.env.company, tracking=True)
    birthdate = fields.Date(string='Дата народження', tracking=True)
    age = fields.Integer(string='Вік', compute='_compute_age', store=False)
    age_category = fields.Selection(
        AGE_CATEGORY, string='Вікова категорія',
        compute='_compute_age_category', store=True,
        help='Використовується для розрахунку капітаційного коефіцієнта НСЗУ.')
    rnokpp = fields.Char(string='РНОКПП', size=10,
                          help='РНОКПП дорослого пацієнта. Для дітей до 14 років — порожнє.')
    birth_certificate_no = fields.Char(string='Свідоцтво про народження',
                                        help='Для дітей віком до 14 років.')
    gender = fields.Selection([('male', 'Чоловіча'), ('female', 'Жіноча')],
                                string='Стать', tracking=True)
    declaration_ids = fields.One2many(
        'l10n_ua.medecin.declaration', 'patient_id', string='Декларації')
    active_declaration_id = fields.Many2one(
        'l10n_ua.medecin.declaration', string='Поточна декларація',
        compute='_compute_active_declaration', store=True)
    active_doctor_id = fields.Many2one(
        'hr.employee', string='Поточний лікар',
        related='active_declaration_id.doctor_id', store=True, readonly=True,
        # A related field inherits `tracking` from its target
        # (declaration.doctor_id is tracked), so it would post a "Поточний
        # лікар" note on the patient every time a declaration changes, even
        # under `tracking_disable` (recompute runs in the flush context).
        # The change is already tracked on the declaration itself.
        tracking=False)
    note = fields.Text(string='Примітки')
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True)

    @api.depends('partner_id', 'patient_card_no')
    def _compute_display_name(self):
        for rec in self:
            base = rec.partner_id.name or _('Пацієнт')
            if rec.patient_card_no:
                rec.display_name = f"{base} (№{rec.patient_card_no})"
            else:
                rec.display_name = base

    @api.depends('birthdate')
    def _compute_age(self):
        today = date.today()
        for rec in self:
            rec.age = relativedelta(today, rec.birthdate).years if rec.birthdate else 0

    @api.depends('birthdate')
    def _compute_age_category(self):
        today = date.today()
        for rec in self:
            if not rec.birthdate:
                rec.age_category = False
                continue
            years = relativedelta(today, rec.birthdate).years
            if years <= 5:
                rec.age_category = '0_5'
            elif years <= 17:
                rec.age_category = '6_17'
            elif years <= 39:
                rec.age_category = '18_39'
            elif years <= 64:
                rec.age_category = '40_64'
            else:
                rec.age_category = '65+'

    @api.model
    def _cron_refresh_age_category(self):
        """Перерахувати вікові категорії: пацієнти старішають без жодної події.

        `age_category` збережене й залежить лише від `birthdate`, а рахується
        від сьогоднішньої дати. Без цього крону категорія назавжди лишається
        такою, якою була на момент заведення пацієнта: дитині виповнюється
        шість, а в базі вона й далі 0–5 із коефіцієнтом 4.0 замість 2.2.

        Для капітації НСЗУ це не косметика — це сума договору. Причому
        помилка одностороння: категорії тільки «дорослішають», тож із часом
        база систематично завищується на дитячих групах і занижується на
        65+, куди ніхто сам не переходить.
        """
        patients = self.search([('birthdate', '!=', False)])
        if not patients:
            return
        self.env.add_to_compute(self._fields['age_category'], patients)
        patients.flush_recordset(['age_category'])

    @api.depends('declaration_ids.state', 'declaration_ids.date_start')
    def _compute_active_declaration(self):
        for rec in self:
            active = rec.declaration_ids.filtered(lambda d: d.state == 'active')
            rec.active_declaration_id = active[:1].id if active else False

    @api.constrains('rnokpp')
    def _check_rnokpp(self):
        for rec in self:
            if rec.rnokpp and (not rec.rnokpp.isdigit() or len(rec.rnokpp) != 10):
                raise ValidationError(_('РНОКПП має бути 10-значним числом.'))

    _patient_card_company_uniq = models.Constraint(
        'unique(patient_card_no, company_id)',
        'Номер медичної картки має бути унікальним у межах закладу!',
    )
