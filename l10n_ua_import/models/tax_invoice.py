from odoo import api, fields, models


class L10nUaTaxInvoice(models.Model):
    _inherit = 'l10n_ua.tax.invoice'

    l10n_ua_import_declaration_id = fields.Many2one(
        'l10n_ua.import.declaration', string='Import Customs Declaration', readonly=True, copy=False,
        index='btree_not_null')

    @api.depends('doc_type', 'number', 'date', 'l10n_ua_import_declaration_id')
    def _compute_name(self):
        super()._compute_name()
        for rec in self.filtered('l10n_ua_import_declaration_id'):
            rec.name = f'МД {rec.number} від {rec.date}'


class L10nUaVatErpnLimit(models.Model):
    _inherit = 'l10n_ua.vat.erpn.limit'

    def action_calculate_from_registers(self):
        """ПДВ з митних декларацій — окремою складовою ΣМитноПДВ, а не ΣОтримПДВ."""
        result = super().action_calculate_from_registers()
        for rec in self:
            registers = self.env['l10n_ua.vat.register'].search([
                ('register_type', '=', 'received'),
                ('state', '=', 'confirmed'),
                ('company_id', '=', rec.company_id.id),
            ])
            import_vat = sum(registers.line_ids.filtered(
                lambda l: l.tax_invoice_id.is_import).mapped('vat_amount'))
            rec.write({
                'amount_import_vat': import_vat,
                'amount_received_vat': rec.amount_received_vat - import_vat,
            })
        return result
