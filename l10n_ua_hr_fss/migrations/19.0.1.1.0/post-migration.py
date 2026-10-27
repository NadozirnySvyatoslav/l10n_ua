"""ФСС → ПФУ у нумерації заяв-розрахунків (#499).

З 01.01.2023 лікарняні з 6-го дня фінансує Пенсійний фонд України, тож нові
документи нумеруються з префіксом «ПФУ/». Послідовність лежить під noupdate,
тому префікс і назву оновлюємо тут — лише там, де вони досі заводські:
префікс, який змінив користувач, не чіпаємо. Номери вже створених документів
(«ФСС/2026/0001») лишаються як є, лічильник послідовності продовжується.
"""

import logging

_logger = logging.getLogger(__name__)

OLD_PREFIX = 'ФСС/%(year)s/'
NEW_PREFIX = 'ПФУ/%(year)s/'
OLD_NAME = 'FSS Settlement'
NEW_NAME = 'PFU Settlement'


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "UPDATE ir_sequence SET prefix = %s"
        " WHERE code = 'hr.fss.settlement' AND prefix = %s",
        (NEW_PREFIX, OLD_PREFIX))
    if cr.rowcount:
        _logger.info('hr.fss.settlement: префікс %s → %s (%d посл.)',
                     OLD_PREFIX, NEW_PREFIX, cr.rowcount)
    cr.execute(
        "UPDATE ir_sequence SET name = %s"
        " WHERE code = 'hr.fss.settlement' AND name = %s",
        (NEW_NAME, OLD_NAME))
