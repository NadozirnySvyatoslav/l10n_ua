from odoo import api, fields, models

# Коди ДК 011-96 для стандартних одиниць Odoo
KSPOVO_CODES = {
    'uom.product_uom_unit': '2009',
    'uom.product_uom_kgm': '0301',
    'uom.product_uom_ton': '0306',
    'uom.product_uom_gram': '0303',
    'uom.product_uom_litre': '0138',
}


class UomUom(models.Model):
    _inherit = 'uom.uom'

    l10n_ua_kspovo_code = fields.Char(
        string='Код КСПОВО', size=4,
        help='Код одиниці виміру за Класифікатором систем позначень одиниць вимірювання та обліку '
             'ДК 011-96 — графа 4.1 податкової накладної.')

    @api.model
    def _l10n_ua_fill_kspovo_codes(self):
        for xmlid, code in KSPOVO_CODES.items():
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom and not uom.l10n_ua_kspovo_code:
                uom.l10n_ua_kspovo_code = code
