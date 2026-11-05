from odoo import fields, models


class StockLandedCost(models.Model):
    _inherit = 'stock.landed.cost'

    l10n_ua_import_declaration_id = fields.Many2one(
        'l10n_ua.import.declaration', string='Import Customs Declaration', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict')


class StockValuationAdjustmentLines(models.Model):
    _inherit = 'stock.valuation.adjustment.lines'

    def _create_account_move_line(self, credit_account_id, debit_account_id, remaining_qty):
        """Кредит розрахунків з митницею (377) — з контрагентом-митницею, щоб
        закрити його авансом, сплаченим на рахунок митниці."""
        commands = super()._create_account_move_line(credit_account_id, debit_account_id, remaining_qty)
        customs = self.cost_id.l10n_ua_import_declaration_id.customs_office_id
        if customs:
            for command in commands:
                if command[2].get('account_id') == credit_account_id:
                    command[2]['partner_id'] = customs.id
        return commands
