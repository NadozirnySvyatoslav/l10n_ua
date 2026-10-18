"""The app icon was redrawn in the Odoo 19 style. A menu keeps the image it read at
install time and an upgrade does not reread an unchanged path, so the new file is
read once more here."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref('l10n_ua_marketplace_base.menu_marketplace_root', raise_if_not_found=False)
    if menu and menu.web_icon:
        menu.web_icon = menu.web_icon
