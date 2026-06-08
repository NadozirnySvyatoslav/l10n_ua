from odoo import models, fields, api


class HrKp2010(models.Model):
    _name = 'hr.kp2010'
    _description = 'Classifier of Professions (KP 2010)'
    _order = 'code'
    _parent_name = 'parent_id'
    _parent_store = True

    code = fields.Char(string='Code', required=True, index=True)
    name = fields.Char(string='Name', required=True, translate=True)
    group_code = fields.Char(string='Group Code', size=1,
                              help='Major group code (1-9)')
    section_code = fields.Char(string='Section Code', size=2)
    work_conditions = fields.Selection([
        ('normal', 'Normal'),
        ('hazardous', 'Hazardous'),
        ('heavy', 'Heavy'),
    ], string='Typical Work Conditions', default='normal')
    active = fields.Boolean(string='Active', default=True)

    # === 4-рівнева ієрархія за ДК 003:2010 (#98) ===
    parent_id = fields.Many2one(
        'hr.kp2010', string='Батьківський запис',
        ondelete='restrict', index=True,
        help='Батьківський рівень в ієрархії ДК 003:2010 (Розділ → Підрозділ → Клас → Професія).',
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('hr.kp2010', 'parent_id', string='Дочірні записи')
    level = fields.Selection([
        ('1', 'Розділ (1 цифра)'),
        ('2', 'Підрозділ (2 цифри)'),
        ('3', 'Клас (3 цифри)'),
        ('4', 'Підклас / Професія (4+)'),
    ], string='Рівень класифікатора',
        compute='_compute_level', store=True, index=True,
        help='Рівень у ієрархії ДК 003:2010, виводиться з довжини коду '
             '(до крапки/тире). Розділ — 1 цифра, Підрозділ — 2, Клас — 3, '
             'Підклас/Професія — 4+ цифр.')

    @api.depends('code')
    def _compute_level(self):
        for rec in self:
            if not rec.code:
                rec.level = False
                continue
            # Strip non-digit suffix (e.g. "2132.2" → "2132") for level calculation
            digits = rec.code.split('.')[0].split('-')[0]
            n = len(digits)
            if n <= 1:
                rec.level = '1'
            elif n == 2:
                rec.level = '2'
            elif n == 3:
                rec.level = '3'
            else:
                rec.level = '4'

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            if record.code and record.name:
                record.display_name = f"[{record.code}] {record.name}"
            elif record.code:
                record.display_name = record.code
            elif record.name:
                record.display_name = record.name
            else:
                record.display_name = ''
