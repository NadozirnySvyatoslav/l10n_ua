from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.l10n_ua_medecin_department import MOVEMENT_KEYS

DAYS_IN_YEAR = 365


class L10nUaMedecinBedReportMixin(models.AbstractModel):
    """Спільні поля звітів по ліжковому фонду (заклад, відділення)."""
    _name = 'l10n_ua.medecin.bed.report.mixin'
    _description = 'Звіт по ліжковому фонду (спільне)'

    company_id = fields.Many2one(
        'res.company', string='Заклад', required=True,
        default=lambda self: self.env.company)
    department_ids = fields.Many2many(
        'l10n_ua.medecin.department', string='Відділення',
        domain="[('company_id', '=', company_id)]",
        help='Порожньо — усі відділення закладу.')

    def _get_departments(self):
        self.ensure_one()
        departments = self.department_ids or self.env['l10n_ua.medecin.department'].search(
            [('company_id', '=', self.company_id.id)])
        if not departments:
            raise UserError(_('У закладі немає відділень стаціонару.'))
        return departments


class L10nUaMedecinReport007o(models.TransientModel):
    """Листок обліку руху хворих і ліжкового фонду стаціонару (ф. 007/о) за добу."""
    _name = 'l10n_ua.medecin.report.007o'
    _inherit = ['l10n_ua.medecin.bed.report.mixin']
    _description = 'Листок руху хворих і ліжкового фонду (ф. 007/о)'

    date = fields.Date(
        string='Дата (доба)', required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        'l10n_ua.medecin.report.007o.line', 'report_id', string='Рядки')

    def action_compute(self):
        for report in self:
            departments = report._get_departments()
            data = departments._get_bed_movement(report.date, report.date)
            lines = []
            total = dict.fromkeys(MOVEMENT_KEYS + ('bed_count', 'bed_free'), 0)
            for seq, dept in enumerate(departments, start=1):
                vals = {k: data[dept.id][k] for k in MOVEMENT_KEYS + ('bed_count',)}
                vals['bed_free'] = max(vals['bed_count'] - vals['count_end'], 0)
                for key in total:
                    total[key] += vals[key]
                lines.append(dict(vals, sequence=seq, department_id=dept.id))
            lines.append(dict(total, sequence=len(lines) + 1, is_total=True))
            report.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in lines]
        return False

    def action_print(self):
        self.action_compute()
        return self.env.ref(
            'l10n_ua_medecin_inpatient.action_report_007o').report_action(self)


class L10nUaMedecinReport007oLine(models.TransientModel):
    _name = 'l10n_ua.medecin.report.007o.line'
    _description = 'Рядок ф. 007/о'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.medecin.report.007o', required=True, ondelete='cascade')
    sequence = fields.Integer()
    is_total = fields.Boolean(string='Разом')
    department_id = fields.Many2one('l10n_ua.medecin.department', string='Відділення')
    bed_count = fields.Integer(string='Ліжок')
    count_start = fields.Integer(string='На початок доби')
    admitted = fields.Integer(string='Поступило')
    transferred_in = fields.Integer(string='Переведено з інших відділень')
    transferred_out = fields.Integer(string='Переведено в інші відділення')
    discharged = fields.Integer(string='Виписано')
    died = fields.Integer(string='Померло')
    count_end = fields.Integer(string='На кінець доби')
    bed_free = fields.Integer(string='Вільних ліжок')
    bed_days = fields.Integer(string='Ліжко-днів')

    @api.depends('department_id', 'is_total')
    def _compute_display_name(self):
        for line in self:
            line.display_name = _('Разом по стаціонару') if line.is_total \
                else line.department_id.display_name


class L10nUaMedecinBedIndicators(models.TransientModel):
    """Показники використання ліжкового фонду за довільний період."""
    _name = 'l10n_ua.medecin.bed.indicators'
    _inherit = ['l10n_ua.medecin.bed.report.mixin']
    _description = 'Показники використання ліжкового фонду'

    date_from = fields.Date(
        string='З', required=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string='По', required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        'l10n_ua.medecin.bed.indicators.line', 'report_id', string='Рядки')

    @staticmethod
    def _indicators(vals, period_days, departed):
        avg_beds = vals['avg_beds']
        bed_days = vals['bed_days']
        left = vals['discharged'] + vals['died']
        occupancy = bed_days / avg_beds if avg_beds else 0.0
        return {
            'departed': departed,
            'occupancy_days': occupancy,
            'occupancy_days_year': occupancy * DAYS_IN_YEAR / period_days,
            'occupancy_pct': occupancy / period_days * 100,
            'bed_turnover': departed / avg_beds if avg_beds else 0.0,
            'avg_stay': bed_days / departed if departed else 0.0,
            'mortality': vals['died'] / left * 100 if left else 0.0,
        }

    def action_compute(self):
        for report in self:
            if report.date_to < report.date_from:
                raise UserError(_('Дата «По» не може бути раніше дати «З».'))
            period_days = (report.date_to - report.date_from).days + 1
            departments = report._get_departments()
            data = departments._get_bed_movement(report.date_from, report.date_to)
            keys = MOVEMENT_KEYS + ('avg_beds',)
            total = dict.fromkeys(keys, 0)
            lines = []
            for seq, dept in enumerate(departments, start=1):
                vals = {k: data[dept.id][k] for k in keys}
                for key in keys:
                    total[key] += vals[key]
                # Відділення: вибулі = виписані + померлі + переведені в інші відділення.
                departed = vals['discharged'] + vals['died'] + vals['transferred_out']
                vals.update(report._indicators(vals, period_days, departed))
                lines.append(dict(vals, sequence=seq, department_id=dept.id))
            # Стаціонар у цілому: внутрішні переведення не є вибуттям.
            departed = total['discharged'] + total['died']
            total.update(report._indicators(total, period_days, departed))
            lines.append(dict(total, sequence=len(lines) + 1, is_total=True))
            report.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in lines]
        return False


class L10nUaMedecinBedIndicatorsLine(models.TransientModel):
    _name = 'l10n_ua.medecin.bed.indicators.line'
    _description = 'Рядок показників ліжкового фонду'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.medecin.bed.indicators', required=True, ondelete='cascade')
    sequence = fields.Integer()
    is_total = fields.Boolean(string='Разом')
    department_id = fields.Many2one('l10n_ua.medecin.department', string='Відділення')
    avg_beds = fields.Float(string='Середнє число ліжок', digits=(16, 2))
    count_start = fields.Integer(string='На початок періоду')
    admitted = fields.Integer(string='Поступило')
    transferred_in = fields.Integer(string='Переведено з інших відділень')
    transferred_out = fields.Integer(string='Переведено в інші відділення')
    discharged = fields.Integer(string='Виписано')
    died = fields.Integer(string='Померло')
    count_end = fields.Integer(string='На кінець періоду')
    departed = fields.Integer(string='Вибуло')
    bed_days = fields.Integer(string='Ліжко-днів')
    occupancy_days = fields.Float(
        string='Днів зайнятості ліжка за період', digits=(16, 1),
        help='Ліжко-дні / середнє число ліжок.')
    occupancy_days_year = fields.Float(
        string='Днів зайнятості ліжка на рік', digits=(16, 1),
        help='Ліжко-дні / середнє число ліжок, приведені до року: × 365 / днів у періоді.')
    occupancy_pct = fields.Float(
        string='Зайнятість ліжок, %', digits=(16, 1),
        help='Ліжко-дні / (середнє число ліжок × днів у періоді) × 100.')
    bed_turnover = fields.Float(
        string='Обіг ліжка', digits=(16, 2),
        help='Вибуло / середнє число ліжок.')
    avg_stay = fields.Float(
        string='Середня тривалість перебування, днів', digits=(16, 1),
        help='Ліжко-дні / вибуло.')
    mortality = fields.Float(
        string='Летальність, %', digits=(16, 2),
        help='Померло / (виписано + померло) × 100.')

    @api.depends('department_id', 'is_total')
    def _compute_display_name(self):
        for line in self:
            line.display_name = _('Разом по стаціонару') if line.is_total \
                else line.department_id.display_name
