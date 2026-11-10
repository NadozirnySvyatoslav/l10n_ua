"""Прив'язати ПН касового методу, складені до поділу по надходженнях (#255).

До цієї версії ПН за касовим методом складалась лише на документ, погашений
одним надходженням, і зв'язку з погашенням не мала. Тепер повторне «Створити
ПН» шукає непокриті погашення за цим зв'язком; без нього стара ПН вважалась
би сиротою й блокувала генерацію. Прив'язуємо лише однозначні випадки — одне
погашення на документі; решту лишаємо людині, генерація пояснить чому.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    legacy = env['l10n_ua.tax.invoice'].search([
        ('vat_method', '=', 'cash'),
        ('doc_type', '=', 'pn'),
        ('move_id', '!=', False),
        ('partial_reconcile_id', '=', False),
        ('state', '!=', 'cancelled'),
    ])
    for move, invoices in legacy.grouped('move_id').items():
        if len(invoices) != 1:
            continue
        settlements = move._l10n_ua_cash_settlements()
        if len(settlements) != 1:
            continue
        invoices.write({
            'partial_reconcile_id': settlements[0]['partial'].id,
            'payment_move_id': settlements[0]['payment_move'].id,
        })
