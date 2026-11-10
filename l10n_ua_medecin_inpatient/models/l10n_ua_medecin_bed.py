from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class L10nUaMedecinBed(models.Model):
    """Ліжко стаціонару (одиниця ліжкового фонду).

    Ліжковий фонд відділення на дату — кількість активних ліжок, розгорнутих
    на цю дату: дата розгортання ≤ дата < дата згортання (порожні дати —
    без обмеження). Згорнуте ліжко лишається в історії й рахується в
    середньорічному числі ліжок за дні, коли воно було розгорнуте.
    Архівування (active = False) прибирає ліжко з обліку повністю — для
    помилково створених записів.
    """
    _name = 'l10n_ua.medecin.bed'
    _description = 'Ліжко стаціонару'
    _order = 'department_id, ward, sequence, name'
    _check_company_auto = True

    name = fields.Char(string='Номер ліжка', required=True)
    ward = fields.Char(string='Палата')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    department_id = fields.Many2one(
        'l10n_ua.medecin.department', string='Відділення', required=True,
        ondelete='restrict', index=True, check_company=True)
    company_id = fields.Many2one(
        related='department_id.company_id', store=True, index=True,
        string='Заклад')
    specialty_id = fields.Many2one(
        'l10n_ua.medecin.specialty', string='Профіль ліжка', ondelete='restrict',
        compute='_compute_specialty_id', store=True, readonly=False,
        help='За замовчуванням — профіль відділення.')
    date_open = fields.Date(
        string='Дата розгортання',
        help='З цієї дати ліжко входить у ліжковий фонд. Порожньо — з початку обліку.')
    date_close = fields.Date(
        string='Дата згортання',
        help='З цієї дати ліжко не входить у ліжковий фонд. Порожньо — діюче.')
    note = fields.Char(string='Примітка')

    admission_id = fields.Many2one(
        'l10n_ua.medecin.admission', string='Пацієнт на ліжку',
        compute='_compute_admission_id')
    is_occupied = fields.Boolean(
        string='Зайняте', compute='_compute_admission_id',
        search='_search_is_occupied')

    _bed_uniq = models.Constraint(
        'unique(department_id, ward, name)',
        'Ліжко з таким номером у цій палаті відділення вже існує.',
    )

    @api.depends('department_id.specialty_id')
    def _compute_specialty_id(self):
        for bed in self:
            if not bed.specialty_id:
                bed.specialty_id = bed.department_id.specialty_id

    @api.depends('ward', 'name', 'department_id')
    def _compute_display_name(self):
        for bed in self:
            parts = []
            if bed.ward:
                parts.append(_('пал. %s', bed.ward))
            parts.append(_('ліжко %s', bed.name or ''))
            label = ', '.join(parts)
            if bed.department_id.code:
                label = f'{bed.department_id.code}: {label}'
            bed.display_name = label

    def _occupying_admissions(self):
        return self.env['l10n_ua.medecin.admission'].search([
            ('bed_id', 'in', self.ids), ('state', '=', 'admitted')])

    def _compute_admission_id(self):
        by_bed = {a.bed_id.id: a for a in self._occupying_admissions()}
        for bed in self:
            adm = by_bed.get(bed.id)
            bed.admission_id = adm
            bed.is_occupied = bool(adm)

    def _search_is_occupied(self, operator, value):
        if operator not in ('=', '!='):
            return NotImplemented
        occupied = self.env['l10n_ua.medecin.admission'].search(
            [('bed_id', '!=', False), ('state', '=', 'admitted')]).bed_id
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', occupied.ids)]

    @api.constrains('date_open', 'date_close')
    def _check_dates(self):
        for bed in self:
            if bed.date_open and bed.date_close and bed.date_close <= bed.date_open:
                raise ValidationError(_(
                    'Дата згортання ліжка має бути пізніше дати розгортання (%s).',
                    bed.display_name))

    def _is_deployed_on(self, day):
        self.ensure_one()
        return (not self.date_open or self.date_open <= day) \
            and (not self.date_close or day < self.date_close)

    def _deployed_days(self, date_from, date_to):
        """Кількість днів у [date_from, date_to], коли ліжко було розгорнуте."""
        self.ensure_one()
        start = max(date_from, self.date_open) if self.date_open else date_from
        # date_close — перший день, коли ліжка вже немає.
        end = min(date_to, fields.Date.subtract(self.date_close, days=1)) \
            if self.date_close else date_to
        return max((end - start).days + 1, 0)
