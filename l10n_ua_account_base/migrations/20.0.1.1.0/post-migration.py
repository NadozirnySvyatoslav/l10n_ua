"""Донести клас 0 базам, де модуль уже стоїть.

`post_init_hook` виконується лише при встановленні модуля (`loading.py`,
`update_operation == 'install'`), а шаблон плану матеріалізується один раз —
коли на компанію ставиться локалізація. Тобто в наявних базах, де
`l10n_ua_account_base` уже встановлений, жоден із двох шляхів не спрацював би,
і позабалансових рахунків там не з'явилось би ніколи.

Викликаємо ту саму функцію, що й хук: вона ідемпотентна й дивиться на кожну
компанію окремо, тож повторний запуск і компанії з уже заведеним класом 0 їй
не шкодять.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_account_base.hooks import ensure_offbalance_accounts


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_offbalance_accounts(env)
