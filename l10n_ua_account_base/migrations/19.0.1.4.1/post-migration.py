"""Оновлення 19.0.1.4.1 (#418): гарантує план рахунків П(С)БО і клас 0 для наявних баз.

Оскільки версію модуля піднято до 19.0.1.4.1 (оновлення назви друкованої форми
«ОСВ по класу 0» та перекладів), кожен бамп версії повинен мати власний
каталог міграції (`test_migration_ships_for_the_current_version`). Функція
`ensure_psbo_chart` ідемпотентна і нічого не дублює.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_account_base.hooks import ensure_psbo_chart


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_psbo_chart(env)
