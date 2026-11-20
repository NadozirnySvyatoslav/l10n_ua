"""План рахунків П(С)БО (#145) — наявним компаніям на `ua_psbo`.

Шаблон матеріалізується лише при встановленні локалізації, тож нові
субрахунки (021–025, 041/042, 071/072, 673–676, 686, 706, 707), аналітику і
субконто наявним компаніям доносить ця міграція. Назви стокових рахунків не
чіпає. Функція ідемпотентна.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_account_base.hooks import ensure_psbo_chart


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_psbo_chart(env)
