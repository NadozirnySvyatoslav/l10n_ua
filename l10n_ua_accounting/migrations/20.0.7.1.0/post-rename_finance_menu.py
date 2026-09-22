"""Застосувати нові підписи меню на вже наявних базах.

Реліз перейменовує рідний апп на «Бухоблік» і змінює кілька власних підписів
(«Доходи і витрати (P&L)», «Звітність», «Довідники»). Ключі мови для цих
записів у базі вже є, тож звичайне завантаження i18n їх не перезапише — див.
hooks.reload_module_terms.
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_accounting.hooks import reload_module_terms


def migrate(cr, version):
    reload_module_terms(api.Environment(cr, SUPERUSER_ID, {}))
