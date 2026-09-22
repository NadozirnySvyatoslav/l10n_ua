"""Наявні ПН отримують те правило визнання, яке до них справді застосовне.

`vat_method` додається з дефолтом 'first_event', тож без цього кроку кожна
вже заведена вхідна ПН і кожен РК стверджували б, що їх датовано за першою
подією. Насправді дата таких документів береться з них самих ('document'):
вхідну ПН склав постачальник за своїм правилом, а РК складається на дату
коригуючої події.

Виправляємо лише те, що поле стверджує про минуле; самі дати не чіпаємо —
вони вже стоять у документах і могли бути виставлені вручну.
"""

import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not column_exists(cr, 'l10n_ua_tax_invoice', 'vat_method'):
        return

    cr.execute("""
        UPDATE l10n_ua_tax_invoice
           SET vat_method = 'document'
         WHERE (invoice_type = 'received' OR doc_type = 'rk')
           AND vat_method IS DISTINCT FROM 'document'
    """)
    if cr.rowcount:
        _logger.info(
            "l10n_ua_account_vat: правило визнання 'document' проставлено "
            "для %s вхідних ПН і РК", cr.rowcount)
