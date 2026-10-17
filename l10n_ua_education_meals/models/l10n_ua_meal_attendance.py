from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .meal_free_rules import universal_free_levels

FREE_BASIS = [
    ('benefit', 'Пільгова категорія'),
    ('universal', 'Одноразове безоплатне (абз. 10 п. 4)'),
    ('none', 'Платне'),
]

MEAL_FIELDS = ('breakfast', 'lunch', 'afternoon', 'dinner')


class L10nUaMealAttendance(models.Model):
    """Облік присутності дітей на харчуванні (для розрахунку фактичних порцій).

    Кількості можна вводити вручну (зведено по групі) або вести поіменний облік
    (``line_ids``, абз. 13 п. 4 Порядку № 305) — тоді кількості та розподіл
    порцій на безоплатні/платні рахуються з рядків.
    """
    _name = 'l10n_ua.meal.attendance'
    _description = 'Відвідуваність харчування'
    _order = 'date desc, group_id'

    date = fields.Date(string='Дата', required=True, default=fields.Date.context_today)
    group_id = fields.Many2one('l10n_ua.education.group', string='Група / клас', required=True)
    company_id = fields.Many2one('res.company',
                                   related='group_id.company_id', store=True, readonly=True)
    enrolled_count = fields.Integer(
        string='Зараховано', compute='_compute_enrolled', store=True,
        help='Кількість дітей у групі станом на дату')
    present_count = fields.Integer(
        string='Присутні', required=True, default=0,
        compute='_compute_from_lines', store=True, readonly=False)
    absent_count = fields.Integer(
        string='Відсутні', compute='_compute_absent', store=True)
    breakfast_count = fields.Integer(
        string='Сніданок (порцій)',
        compute='_compute_from_lines', store=True, readonly=False)
    lunch_count = fields.Integer(
        string='Обід (порцій)',
        compute='_compute_from_lines', store=True, readonly=False)
    afternoon_count = fields.Integer(
        string='Полуденок (порцій)',
        compute='_compute_from_lines', store=True, readonly=False)
    dinner_count = fields.Integer(
        string='Вечеря (порцій)',
        compute='_compute_from_lines', store=True, readonly=False)
    note = fields.Char(string='Примітка')

    line_ids = fields.One2many(
        'l10n_ua.meal.attendance.line', 'attendance_id', string='Поіменний облік')
    free_portion_count = fields.Integer(
        string='Безоплатних порцій', compute='_compute_free_paid', store=True)
    free_benefit_portion_count = fields.Integer(
        string='з них за пільговими категоріями', compute='_compute_free_paid', store=True)
    free_universal_portion_count = fields.Integer(
        string='з них одноразове безоплатне', compute='_compute_free_paid', store=True)
    paid_portion_count = fields.Integer(
        string='Платних порцій', compute='_compute_free_paid', store=True)
    free_pupil_count = fields.Integer(
        string='Харчувались безоплатно (осіб)', compute='_compute_free_paid', store=True)

    @api.depends('group_id')
    def _compute_enrolled(self):
        for rec in self:
            rec.enrolled_count = rec.group_id.member_count if rec.group_id else 0

    @api.depends('enrolled_count', 'present_count')
    def _compute_absent(self):
        for rec in self:
            rec.absent_count = max(0, rec.enrolled_count - rec.present_count)

    @api.depends('line_ids.present', *(f'line_ids.{m}' for m in MEAL_FIELDS))
    def _compute_from_lines(self):
        # Без поіменного обліку значення вводяться вручну і не перераховуються.
        for rec in self:
            if not rec.line_ids:
                continue
            present = rec.line_ids.filtered('present')
            rec.present_count = len(present)
            for meal in MEAL_FIELDS:
                rec[f'{meal}_count'] = len(present.filtered(meal))

    @api.depends('line_ids.free_basis', 'line_ids.free_count', 'line_ids.paid_count')
    def _compute_free_paid(self):
        for rec in self:
            lines = rec.line_ids
            benefit = lines.filtered(lambda line: line.free_basis == 'benefit')
            universal = lines.filtered(lambda line: line.free_basis == 'universal')
            rec.free_benefit_portion_count = sum(benefit.mapped('free_count'))
            rec.free_universal_portion_count = sum(universal.mapped('free_count'))
            rec.free_portion_count = (rec.free_benefit_portion_count
                                      + rec.free_universal_portion_count)
            rec.paid_portion_count = sum(lines.mapped('paid_count'))
            rec.free_pupil_count = len(lines.filtered(lambda line: line.free_count))

    def action_fill_lines(self):
        """Заповнити поіменний облік учнями групи (зараховані / навчаються)."""
        Line = self.env['l10n_ua.meal.attendance.line']
        for rec in self:
            members = rec.group_id.member_ids.filtered(
                lambda m: m.state in ('enrolled', 'studying'))
            members -= rec.line_ids.member_id
            Line.create([{'attendance_id': rec.id, 'member_id': m.id} for m in members])
        return True

    _date_group_uniq = models.Constraint(
        'unique(date, group_id)',
        'На одну групу — один запис відвідуваності на день!',
    )


class L10nUaMealAttendanceLine(models.Model):
    """Поіменний облік харчування учня за день."""
    _name = 'l10n_ua.meal.attendance.line'
    _description = 'Поіменний облік харчування'
    _order = 'attendance_id, member_id'

    attendance_id = fields.Many2one(
        'l10n_ua.meal.attendance', required=True, ondelete='cascade', index=True)
    date = fields.Date(related='attendance_id.date', store=True)
    company_id = fields.Many2one(related='attendance_id.company_id', store=True)
    member_id = fields.Many2one(
        'l10n_ua.education.contingent.member', string='Учень / вихованець',
        required=True, ondelete='restrict')
    present = fields.Boolean(string='Присутній', default=True)
    breakfast = fields.Boolean(string='Сніданок')
    lunch = fields.Boolean(string='Обід', default=True)
    afternoon = fields.Boolean(string='Полуденок')
    dinner = fields.Boolean(string='Вечеря')

    benefit_category_id = fields.Many2one(
        'l10n_ua.meal.benefit.category', string='Пільгова категорія',
        compute='_compute_free', store=True)
    free_basis = fields.Selection(
        FREE_BASIS, string='Підстава', compute='_compute_free', store=True)
    free_count = fields.Integer(string='Безоплатно, порцій',
                                compute='_compute_free', store=True)
    paid_count = fields.Integer(string='Платно, порцій',
                                compute='_compute_free', store=True)

    @api.depends('present', *MEAL_FIELDS, 'attendance_id.date',
                 'attendance_id.group_id.level', 'attendance_id.group_id.group_type',
                 'member_id.member_type', 'member_id.meal_benefit_ids.category_id',
                 'member_id.meal_benefit_ids.date_from', 'member_id.meal_benefit_ids.date_to')
    def _compute_free(self):
        # Налаштування закладу (форма власності, рішення засновника) навмисно не в
        # depends: їх зміна не переписує вже сформований облік попередніх днів.
        for line in self:
            on_date = line.attendance_id.date
            taken = [m for m in MEAL_FIELDS if line.present and line[m]]
            benefit = line.member_id._l10n_ua_meal_benefit_on(on_date) \
                if line.member_id and on_date else self.env['l10n_ua.meal.benefit']
            line.benefit_category_id = benefit.category_id
            if benefit:
                line.free_basis = 'benefit'
                line.free_count, line.paid_count = len(taken), 0
            elif line._is_universal_free(on_date) and ('breakfast' in taken or 'lunch' in taken):
                line.free_basis = 'universal'
                line.free_count, line.paid_count = 1, len(taken) - 1
            else:
                line.free_basis = 'none'
                line.free_count, line.paid_count = 0, len(taken)

    def _is_universal_free(self, on_date):
        self.ensure_one()
        group = self.attendance_id.group_id
        if group.group_type != 'class' or self.member_id.member_type != 'pupil':
            return False
        company = self.attendance_id.company_id or self.env.company
        levels = universal_free_levels(
            on_date, company.l10n_ua_education_is_state,
            company.l10n_ua_meal_universal_scope)
        return group.level in levels

    _attendance_member_uniq = models.Constraint(
        'unique(attendance_id, member_id)',
        'Учень уже є в поіменному обліку цього дня!',
    )

    @api.constrains('member_id', 'attendance_id')
    def _check_member_group(self):
        for line in self:
            if line.member_id.group_id and line.member_id.group_id != line.attendance_id.group_id:
                raise ValidationError(_(
                    'Учень %(m)s не належить до групи %(g)s.',
                    m=line.member_id.display_name, g=line.attendance_id.group_id.name))
