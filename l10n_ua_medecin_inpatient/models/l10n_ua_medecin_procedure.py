from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


ANESTHESIA_TYPE = [
    ('none', 'Без знеболення'),
    ('local', 'Місцева'),
    ('regional', 'Регіонарна (спінальна, епідуральна, провідникова)'),
    ('sedation', 'Седація'),
    ('general', 'Загальна (наркоз)'),
    ('combined', 'Комбінована'),
]


class L10nUaMedecinProcedureType(models.Model):
    """Довідник медичних втручань (#225).

    Призначений для класифікатора медичних втручань НК 026:2021 (АКМВ,
    українська адаптація ACHI). У модулі сам класифікатор не постачається —
    довідник заповнюється імпортом (код + назва). Окрема модель, а не текст:
    код втручання поряд із заключним діагнозом — вхід групувальника ДСГ.
    """
    _name = 'l10n_ua.medecin.procedure.type'
    _description = 'Медичне втручання (довідник)'
    _order = 'code'
    _rec_names_search = ['code', 'name']

    code = fields.Char(string='Код', required=True, index=True,
                       help='Код втручання, напр. за НК 026:2021 (АКМВ).')
    name = fields.Char(string='Назва', required=True)
    is_surgical = fields.Boolean(string='Хірургічне', default=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Опис')

    _code_uniq = models.Constraint(
        'unique(code)',
        'Код медичного втручання має бути унікальним.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name


class L10nUaMedecinProcedure(models.Model):
    """Медичне (хірургічне) втручання в межах епізоду стаціонару (#225)."""
    _name = 'l10n_ua.medecin.procedure'
    _description = 'Медичне втручання'
    _order = 'date desc, id desc'
    _check_company_auto = True

    admission_id = fields.Many2one(
        'l10n_ua.medecin.admission', string='Епізод стаціонару', required=True,
        ondelete='cascade', index=True)
    procedure_type_id = fields.Many2one(
        'l10n_ua.medecin.procedure.type', string='Втручання (код)', required=True,
        ondelete='restrict', index=True)
    code = fields.Char(related='procedure_type_id.code', store=True, string='Код')
    name = fields.Char(
        string='Назва', compute='_compute_name', store=True, readonly=False,
        precompute=True, required=True,
        help='За замовчуванням — назва з довідника; можна уточнити.')
    date = fields.Datetime(string='Дата і час', required=True,
                           default=fields.Datetime.now)
    surgeon_id = fields.Many2one(
        'hr.employee', string='Хірург (виконавець)', required=True,
        ondelete='restrict', index=True, check_company=True)
    anesthesiologist_id = fields.Many2one(
        'hr.employee', string='Анестезіолог', ondelete='restrict',
        check_company=True)
    anesthesia_type = fields.Selection(
        ANESTHESIA_TYPE, string='Вид знеболення', default='none', required=True)
    is_emergency = fields.Boolean(string='Екстрене')
    has_complication = fields.Boolean(string='Ускладнення після втручання')
    complication_note = fields.Text(string='Опис ускладнення')
    note = fields.Text(string='Примітка')

    patient_id = fields.Many2one(related='admission_id.patient_id', store=True,
                                 index=True, string='Пацієнт')
    department_id = fields.Many2one(related='admission_id.department_id',
                                    store=True, string='Відділення')
    company_id = fields.Many2one(related='admission_id.company_id', store=True,
                                 index=True, string='Заклад')

    @api.depends('procedure_type_id')
    def _compute_name(self):
        for rec in self:
            if rec.procedure_type_id:
                rec.name = rec.procedure_type_id.name

    @api.constrains('date', 'admission_id')
    def _check_date_within_admission(self):
        for rec in self:
            adm = rec.admission_id
            if rec.date < adm.date_admission or (
                    adm.date_discharge and rec.date > adm.date_discharge):
                raise ValidationError(_(
                    'Дата втручання «%(name)s» має бути в межах епізоду '
                    'стаціонарного лікування %(adm)s.',
                    name=rec.name, adm=adm.name))
