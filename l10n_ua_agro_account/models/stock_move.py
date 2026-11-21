from odoo import fields, models


class StockMove(models.Model):
    """Вартість оприбуткованого врожаю на складі = його оцінка за П(С)БО 30.

    Без цього склад оцінює рух з виробничої локації за ``standard_price``
    продукту (часто 0), а проводка Дт 27 іде окремо — вартість залишків і
    сальдо 27 розходяться, і закриття складу (``action_close_stock_valuation``)
    проводить різницю, знімаючи оцінку врожаю з 27 (#603).
    """
    _inherit = 'stock.move'

    l10n_ua_agro_harvest_receipt_ids = fields.One2many(
        'l10n_ua.agro.harvest.receipt', 'move_id', string='Harvest Receipt', readonly=True)

    def _get_value_from_production(self, quantity, at_date=None):
        receipt = self.l10n_ua_agro_harvest_receipt_ids[:1]
        value = receipt._l10n_ua_agro_stock_value() if receipt else 0.0
        valued_qty = self._get_valued_qty() if receipt else 0.0
        if not receipt or not valued_qty or receipt.company_id.currency_id.is_zero(value):
            return super()._get_value_from_production(quantity, at_date)
        return {
            'value': value * quantity / valued_qty,
            'quantity': quantity,
            'description': self.env._('Harvest %(receipt)s valued under P(S)BO 30', receipt=receipt.name),
        }

    def _should_create_account_move(self):
        # первісне визнання проводить оприбуткування (Дт 27 — Кт 710 / 23);
        # складська проводка того ж руху задвоїла б Дт 27
        if self.l10n_ua_agro_harvest_receipt_ids:
            return False
        return super()._should_create_account_move()
