"""#603: вартість уже оприбуткованого врожаю на складі — за його оцінкою.

До цієї версії вхідний рух урожаю оцінювався за ``standard_price`` товару
(часто 0), а Дт 27 проводився окремо. Перераховуємо вартість рухів за
оцінкою оприбуткування і розносимо на оприбуткування доведення планової
собівартості з уже проведених калькуляцій. Проводки не змінюються.
Товари зі стандартною ціною пропускаються: їх залишок склад оцінює за ціною
товару, тож категорію треба перевести на AVCO/FIFO вручну.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    receipts = env['l10n_ua.agro.harvest.receipt'].search([
        ('state', '=', 'done'), ('account_move_id', '!=', False), ('move_id', '!=', False)])
    skipped = receipts.filtered(
        lambda r: r.product_id.with_company(r.company_id).cost_method == 'standard')
    if skipped:
        _logger.warning(
            'Harvest receipts of standard-priced products are not revalued (set AVCO/FIFO on the '
            'category): %s', ', '.join(skipped.mapped('name')))
    receipts -= skipped
    calcs = env['l10n_ua.agro.cost.calculation'].search([('state', '=', 'posted')])
    for calc in calcs.filtered(lambda c: c.valuation_method == 'planned_cost'):
        for parts in calc._harvest_adjustments().values():
            for receipt, amount in parts:
                if receipt in receipts:
                    receipt.write({'cost_adjustment': amount, 'cost_calculation_id': calc.id})
    receipts._revalue_stock()
    _logger.info('Revalued the stock moves of %s harvest receipts', len(receipts))
