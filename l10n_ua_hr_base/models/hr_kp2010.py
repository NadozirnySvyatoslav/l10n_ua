import csv
import json
import logging

from odoo import models, fields, api
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

# Офіційні назви розділів, підрозділів і класів ДК 003:2010 — розділ 5
# «Класифікація професій» тексту класифікатора (Додаток А, редакція на
# zakon.rada.gov.ua, va327609-10). Професій тут немає, вони в
# hr_kp2010_data.xml.
LEVELS_FILE = 'l10n_ua_hr_base/data/hr_kp2010_levels.csv'

# Так рівні називались, поки офіційних назв у модулі не було. Запис із такою
# назвою — заглушка, яку можна замінити; будь-яку іншу назву вписала людина.
PLACEHOLDER_PREFIX = {1: 'Розділ', 2: 'Підрозділ', 3: 'Клас'}


def _placeholder_name(code):
    prefix = PLACEHOLDER_PREFIX.get(len(code or ''))
    return prefix and f'{prefix} {code}'


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

    @api.model
    def _l10n_ua_build_hierarchy(self):
        """Добудувати рівні класифікатора й проставити батьків.

        Дані модуля везуть самі професії — 9144 записи з кодами на чотири й
        шість символів. Рівнів вище (розділ, підрозділ, клас) у ДК 003:2010
        окремими рядками немає, вони виводяться з коду: 2132.2 належить
        класу 213, підрозділу 21 і розділу 2.

        Досі це робила лише міграція `19.0.1.0.5`, а міграції на чистій
        установці не виконуються — тобто в кожній новій базі класифікатор
        лишався плоским списком з дев'яти тисяч позицій, де вибір посади
        зводиться до пошуку по підрядку. Метод викликає й хук установки, і
        міграція, тож обидва шляхи дають однаковий результат.

        Ідемпотентний і тихий на повторному запуску: створює лише відсутні
        рівні й пише `parent_id` тільки тим записам, у яких він інший, —
        інакше кожне оновлення модуля переписувало б дев'ять тисяч рядків
        заради тих самих значень.
        """
        records = self.with_context(active_test=False).search_read(
            [], ['code', 'parent_id'], load='')
        if not records:
            return

        def digits_of(code):
            return (code or '').split('.')[0].split('-')[0]

        by_code = {}
        current_parent = {}
        for record in records:
            by_code.setdefault(record['code'], []).append(record['id'])
            current_parent[record['id']] = record['parent_id'] or False

        # Рівні, яких бракує: усі власні префікси наявних кодів.
        needed = set()
        for code in by_code:
            digits = digits_of(code)
            for length in (1, 2, 3):
                if length < len(digits):
                    needed.add(digits[:length])
        missing = sorted(needed - set(by_code), key=lambda c: (len(c), c))

        # Назва — офіційна, де ДК 003:2010 її дає. Кілька класів із даних
        # модуля (619, 799, 899 та підрозділи 79, 89) в опублікованому тексті
        # не названі — вони лишаються з номером, а не з вигаданою назвою.
        official = self._l10n_ua_level_names()
        for created in self.create([
            {'code': code,
             'name': official.get(code) or _placeholder_name(code),
             'group_code': code[0]}
            for code in missing
        ]):
            by_code.setdefault(created.code, []).append(created.id)
            current_parent[created.id] = False

        # Батько — найдовший наявний префікс, коротший за сам код. Один код
        # може мати кілька записів (у класифікаторі є однакові коди різних
        # професій) — батьком для всіх стає найперший із них.
        parent_of_code = {}
        for code in by_code:
            digits = digits_of(code)
            for length in range(len(digits) - 1, 0, -1):
                candidate = digits[:length]
                if candidate in by_code and candidate != code:
                    parent_of_code[code] = min(by_code[candidate])
                    break

        # Групуємо за батьком: кілька сотень записів замість дев'яти тисяч.
        children_of_parent = {}
        for code, parent_id in parent_of_code.items():
            children_of_parent.setdefault(parent_id, []).extend(
                child_id for child_id in by_code[code]
                if child_id != parent_id
                and current_parent.get(child_id) != parent_id)
        reparented = 0
        for parent_id, child_ids in children_of_parent.items():
            # Батько виводиться з коду, тож ручне перепідпорядкування тут
            # перекривається — інакше запис із чужим батьком назавжди лишався
            # б поза своєю гілкою. Але тихо цього робити не варто: скільки
            # записів переїхало, видно в лозі.
            existing = [child_id for child_id in child_ids
                        if current_parent.get(child_id)]
            reparented += len(existing)
            self.browse(child_ids).write({'parent_id': parent_id})
        if reparented:
            _logger.info(
                'КП-2010: %s запис(ів) перепідпорядковано за кодом — '
                'попереднього батька, зокрема виставленого вручну, замінено',
                reparented)

        self._l10n_ua_name_levels()

    @api.model
    def _l10n_ua_level_names(self):
        """Код рівня → офіційна назва за ДК 003:2010."""
        with file_open(LEVELS_FILE) as levels:
            return {row['code']: row['name'] for row in csv.DictReader(levels)}

    @api.model
    def _l10n_ua_name_levels(self):
        """Дати офіційні назви рівням, що досі звуться «Розділ 2».

        Бази, де ієрархію побудовано до появи назв, мають ~180 заглушок —
        хуком або міграцією 19.0.1.0.5, яка писала заглушку і в en_US, і в
        uk_UA. Замінюється лише та мова, де лежить саме заглушка: назву, яку
        кадровик виправив руками, не чіпаємо. Викликається з даних модуля,
        тож спрацьовує на кожному оновленні, і нічого не пише, коли
        заглушок уже немає.
        """
        official = self._l10n_ua_level_names()
        self.flush_model(['code', 'name', 'level'])
        self.env.cr.execute(
            "SELECT id, code, name FROM hr_kp2010 WHERE level IN ('1', '2', '3')")
        renamed = []
        for record_id, code, names in self.env.cr.fetchall():
            if code not in official or not names:
                continue
            placeholder = _placeholder_name(code)
            if not placeholder:
                continue
            update = {lang: official[code] for lang, value in names.items()
                      if value == placeholder}
            if not update:
                continue
            self.env.cr.execute(
                'UPDATE hr_kp2010 SET name = name || %s::jsonb WHERE id = %s',
                (json.dumps(update), record_id))
            renamed.append(record_id)
        if renamed:
            self.invalidate_model(['name'])
            # Посади, що вже стоять на рівні, тримають його назву в
            # збереженому kp_name — інакше там лишився б «Розділ 2».
            self.env['hr.job'].sudo().with_context(active_test=False).search(
                [('kp_id', 'in', renamed)])._compute_kp_fields()
            _logger.info('КП-2010: %s рівн(ів) отримали офіційні назви '
                         'ДК 003:2010 замість номерів', len(renamed))
        return len(renamed)

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
