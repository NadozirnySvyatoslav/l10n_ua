from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class L10nUaMealBenefitCategory(models.Model):
    """Пільгова категорія на безоплатне гаряче харчування (п. 4 Порядку № 305)."""
    _name = 'l10n_ua.meal.benefit.category'
    _description = 'Пільгова категорія харчування'
    _order = 'sequence, name'

    name = fields.Char(string='Категорія', required=True)
    code = fields.Char(string='Код')
    sequence = fields.Integer(default=10)
    legal_basis = fields.Char(string='Підстава')
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique(code)',
        'Код пільгової категорії має бути унікальним!',
    )


class L10nUaMealBenefit(models.Model):
    """Період права учня на безоплатне гаряче харчування за пільговою категорією."""
    _name = 'l10n_ua.meal.benefit'
    _description = 'Право на пільгове харчування'
    _order = 'date_from desc'

    member_id = fields.Many2one(
        'l10n_ua.education.contingent.member', string='Учень / вихованець',
        required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='member_id.company_id', store=True, readonly=True)
    category_id = fields.Many2one(
        'l10n_ua.meal.benefit.category', string='Пільгова категорія',
        required=True, ondelete='restrict')
    date_from = fields.Date(string='Діє з', required=True)
    date_to = fields.Date(string='Діє по')
    document = fields.Char(
        string='Підтвердний документ',
        help='Документ, що підтверджує право на безоплатне гаряче харчування '
             '(абз. 12 п. 4 Порядку № 305): номер, дата, ким видано.')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_('Дата закінчення пільги раніша за дату початку.'))

    def _covers(self, on_date):
        self.ensure_one()
        return self.date_from <= on_date and (not self.date_to or self.date_to >= on_date)


class L10nUaEducationContingentMember(models.Model):
    _inherit = 'l10n_ua.education.contingent.member'

    meal_benefit_ids = fields.One2many(
        'l10n_ua.meal.benefit', 'member_id', string='Пільги на харчування')

    def _l10n_ua_meal_benefit_on(self, on_date):
        """Пільга на харчування, чинна на дату (перша з чинних) або порожній запис."""
        self.ensure_one()
        return self.meal_benefit_ids.filtered(lambda b: b._covers(on_date))[:1]
