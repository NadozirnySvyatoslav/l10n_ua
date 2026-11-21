from odoo import _, api, fields, models


PACKAGE_TYPE = [
    ('pmd_capitation', 'ПМД — капітація на пацієнта'),
    ('specialized', 'Спеціалізована амбулаторна'),
    ('hospital', 'Стаціонарна'),
    ('emergency', 'Екстрена медична допомога'),
    ('childbirth', 'Пологова допомога'),
    ('cancer', 'Онкологічна допомога'),
    ('mental', 'Психіатрична допомога'),
    ('rehab', 'Реабілітаційні послуги'),
    ('dental', 'Стоматологічна допомога'),
    ('other', 'Інше'),
]

PAYMENT_MODEL = [
    ('capitation', 'Капітація'),
    ('global', 'Глобальний бюджет'),
    ('per_case', 'За випадок'),
    ('per_service', 'За послугу'),
    ('mixed', 'Змішана'),
]


class L10nUaMedecinNszuPackage(models.Model):
    """Пакет медичних послуг НСЗУ.

    Перелік пакетів регулярно оновлюється Наказами НСЗУ — це довідник, що
    потрібно акуратно синхронізувати з офіційним джерелом раз на рік.
    """
    _name = 'l10n_ua.medecin.nszu.package'
    _description = 'Пакет медичних послуг НСЗУ'
    _order = 'year desc, code'
    _rec_name = 'display_name'

    code = fields.Char(string='Код пакету', required=True, index=True,
                       help='Внутрішній код пакету за специфікацією НСЗУ')
    name = fields.Char(string='Назва', required=True, translate=True)
    package_type = fields.Selection(PACKAGE_TYPE, string='Тип', required=True)
    payment_model = fields.Selection(PAYMENT_MODEL, string='Модель оплати', required=True,
                                       default='capitation')
    year = fields.Integer(string='Рік', required=True,
                           default=lambda self: fields.Date.today().year,
                           help='Рік, у якому затверджені специфікації пакета')
    base_tariff = fields.Monetary(
        string='Базовий тариф', currency_field='currency_id',
        help='Базовий тариф НСЗУ на одиницю (наприклад, на одну декларацію в рік для ПМД-капітації).')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    tariff_to_confirm = fields.Boolean(
        string='Тариф потребує підтвердження',
        help='Тариф не звірено з чинною постановою КМУ / наказом НСЗУ про ПМГ '
             '(або взято з попереднього року). Перевірте перед укладанням договору.')
    description = fields.Html(string='Специфікація')
    is_active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('code', 'name', 'year')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name} ({rec.year})"

    _code_year_uniq = models.Constraint(
        'unique(code, year)',
        'Код пакету має бути унікальним для одного року!',
    )

    def action_open_copy_wizard(self):
        """Open the wizard that copies packages to another (next) year."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Копіювати пакети на інший рік'),
            'res_model': 'l10n_ua.medecin.nszu.package.copy.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': self._name,
                'active_ids': self.ids,
            },
        }
