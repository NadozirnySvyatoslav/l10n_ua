"""Вид нарахування SICK_FSS: «за рахунок ФСС» → «за рахунок ПФУ» (#499).

З 01.01.2023 допомогу по тимчасовій непрацездатності з 6-го дня фінансує
Пенсійний фонд України. Запис лежить під noupdate, тож назву й опис
оновлюємо тут — лише ті переклади (мови), де значення досі заводське;
назву, яку змінив користувач, не перезаписуємо. Код SICK_FSS і xml id
лишаються — на них спираються розрахунок і звітність.
"""

import json
import logging

_logger = logging.getLogger(__name__)

XMLID = 'accrual_type_sick_fss'
OLD_NAME = 'Лікарняні (за рахунок ФСС)'
NEW_NAME = 'Лікарняні (за рахунок ПФУ)'
OLD_DESCRIPTION = 'Допомога по тимчасовій непрацездатності за рахунок ФСС'
NEW_DESCRIPTION = ('Допомога по тимчасовій непрацездатності за рахунок ПФУ '
                   '(з 6-го дня)')


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT res_id FROM ir_model_data"
        " WHERE module = 'l10n_ua_hr_salary' AND name = %s"
        " AND model = 'hr.accrual.type'", (XMLID,))
    row = cr.fetchone()
    if not row:
        return
    res_id = row[0]
    cr.execute("SELECT name, description FROM hr_accrual_type WHERE id = %s",
               (res_id,))
    row = cr.fetchone()
    if not row:
        return
    name, description = row
    if isinstance(name, str):
        name = json.loads(name)
    changed = {lang: NEW_NAME for lang, value in (name or {}).items()
               if value == OLD_NAME}
    if changed:
        name.update(changed)
        cr.execute("UPDATE hr_accrual_type SET name = %s::jsonb WHERE id = %s",
                   (json.dumps(name, ensure_ascii=False), res_id))
        _logger.info('SICK_FSS: назву оновлено для мов %s', sorted(changed))
    if description == OLD_DESCRIPTION:
        cr.execute(
            "UPDATE hr_accrual_type SET description = %s WHERE id = %s",
            (NEW_DESCRIPTION, res_id))
