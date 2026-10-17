import csv
import io
import logging

from odoo import api, fields, models
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

NK025_CSV = 'l10n_ua_medecin_clinical/data/nk025_2021.csv'

LEVELS = [
    ('chapter', 'Клас'),
    ('block', 'Блок'),
    ('category', 'Рубрика (3 знаки)'),
    ('subcategory', 'Підрубрика (4 знаки)'),
    ('subcategory5', 'Підрубрика (5 знаків)'),
]
LEVEL_ORDER = [lvl for lvl, _label in LEVELS]


class L10nUaMedecinIcd10(models.Model):
    """МКХ-10 довідник — НК 025:2021 «Класифікатор хвороб та споріднених
    проблем охорони здоров'я» (гармонізований з ICD-10-AM).

    Ієрархія (_parent_store): клас → блок(и) → рубрика → підрубрика(и).
    """
    _name = 'l10n_ua.medecin.icd10'
    _description = 'МКХ-10 код'
    _parent_store = True
    _parent_name = 'parent_id'
    _order = 'code'
    _rec_name = 'display_name'

    code = fields.Char(string='Код', required=True, index=True,
                       help='Формат: A00.0, B15-B19 (блок) тощо')
    name = fields.Char(string='Назва', required=True, translate=True)
    block = fields.Char(string='Блок', help='Наприклад A00-A09')
    level = fields.Selection(LEVELS, string='Рівень')
    is_selectable = fields.Boolean(
        string='Допустимий як діагноз', default=True,
        help='Код найнижчого рівня деталізації (не має підрубрик). '
             'Класи, блоки та рубрики з підрубриками для кодування '
             'заключного діагнозу не використовуються.')
    parent_id = fields.Many2one('l10n_ua.medecin.icd10', ondelete='cascade', index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('l10n_ua.medecin.icd10', 'parent_id')
    description = fields.Text(string='Опис')
    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True,
                               index='trigram')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name

    _code_uniq = models.Constraint(
        'unique(code)',
        'Код МКХ-10 має бути унікальним!',
    )

    @api.model
    def _load_nk025(self, csv_path=NK025_CSV):
        """Ідемпотентне завантаження НК 025:2021 з CSV.

        Існуючі записи (зокрема 27 стартових з xml-id ``icd10_*``) оновлюються
        за кодом на місці, відсутні — створюються пакетно рівень за рівнем,
        тож посилання з діагнозів/станів зберігаються. Записи, яких немає в
        класифікаторі (користувацькі коди), не чіпаються.
        """
        with file_open(csv_path, 'rb') as f:
            rows = list(csv.DictReader(io.StringIO(f.read().decode('utf-8'))))
        self.env.cr.execute('SELECT code, id FROM l10n_ua_medecin_icd10')
        ids_by_code = dict(self.env.cr.fetchall())
        Model = self.with_context(active_test=False, tracking_disable=True)
        existing = {rec.code: rec for rec in Model.browse(list(ids_by_code.values()))}

        by_level = {lvl: [] for lvl in LEVEL_ORDER}
        for row in rows:
            by_level[row['level']].append(row)
        has_children = {row['parent_code'] for row in rows if row['parent_code']}

        def vals_of(row):
            return {
                'code': row['code'],
                'name': row['name'],
                'level': row['level'],
                'block': row['block'] or False,
                'parent_id': ids_by_code.get(row['parent_code'], False),
                'is_selectable': (row['level'] not in ('chapter', 'block')
                                  and row['code'] not in has_children),
            }

        created = updated = 0
        # Ієрархія блоків вкладена (надблоки → блоки), тому кожен рівень
        # обробляється хвилями: спершу записи, чий батько вже існує.
        for lvl in LEVEL_ORDER:
            pending = by_level[lvl]
            while pending:
                ready, waiting = [], []
                for r in pending:
                    if not r['parent_code'] or r['parent_code'] in ids_by_code:
                        ready.append(r)
                    else:
                        waiting.append(r)
                if not ready:
                    raise ValueError('НК 025:2021: невідомі батьківські коди %s'
                                     % sorted({r['parent_code'] for r in waiting}))
                pending = waiting
                to_create = []
                for row in ready:
                    vals = vals_of(row)
                    rec = existing.get(row['code'])
                    if rec is None:
                        to_create.append(vals)
                        continue
                    diff = {}
                    for key, value in vals.items():
                        current = rec[key]
                        if key == 'parent_id':
                            current = current.id
                        if (current or False) != (value or False):
                            diff[key] = value
                    if diff:
                        rec.write(diff)
                        updated += 1
                if to_create:
                    new = Model.create(to_create)
                    ids_by_code.update(zip(new.mapped('code'), new.ids))
                    created += len(new)
                    # На існуючій БД статистика планувальника знята з 27
                    # записів: без ANALYZE підзапити parent_path та UPDATE
                    # обчислюваних полів ідуть seq scan-ом (×10 повільніше).
                    new.flush_model()
                    self.env.cr.execute('ANALYZE l10n_ua_medecin_icd10')
        _logger.info('НК 025:2021: створено %s, оновлено %s записів МКХ-10',
                     created, updated)
        return created, updated
