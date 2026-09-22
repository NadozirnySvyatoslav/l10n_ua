"""Застосувати новий підпис кореня застосунку на вже наявних базах.

Реліз перейменовує «Банк UA» на «Банк». Ключ мови для `menu_ua_bank_root`
у базі вже є, тож звичайне завантаження i18n його не перезапише — див.
hooks.reload_module_terms.
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_bank_sync.hooks import reload_module_terms


def migrate(cr, version):
    reload_module_terms(api.Environment(cr, SUPERUSER_ID, {}))
