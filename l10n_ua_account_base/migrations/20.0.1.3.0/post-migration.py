"""Те саме, що й у попередніх каталогах — клас 0 базам, які його ще не мають.

Odoo виконує каталог міграції лише коли версія в базі менша за його номер, тож
кожен бамп версії потребує власного каталогу: інакше база, що вже стоїть на
попередній, пройде повз усі наявні. Саме це стереже
`test_migration_ships_for_the_current_version`.

Функція ідемпотентна й дивиться на кожну компанію окремо, тож база, що пройде
кілька каталогів поспіль, нічого не подвоїть.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_account_base.hooks import ensure_offbalance_accounts


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_offbalance_accounts(env)
