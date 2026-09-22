"""Те саме, що й у 20.0.1.1.0 — клас 0 базам, які його ще не мають.

Odoo виконує каталог міграції лише коли версія в базі менша за його номер, тож
міграція 1.1.0 добере рахунки базі, що стояла на 1.0.x, і мовчки пропустить
базу, яка вже на 1.1.0. Оскільки версію бампнуто, каталог має бути й на неї —
саме це стереже `test_migration_ships_for_the_current_version`.

Функція ідемпотентна й дивиться на кожну компанію окремо, тож база, що пройде
обидва каталоги поспіль, нічого не подвоїть.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_account_base.hooks import ensure_offbalance_accounts


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_offbalance_accounts(env)
