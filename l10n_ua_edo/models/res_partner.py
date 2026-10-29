from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_ua_edo_account_id = fields.Many2one(
        'l10n_ua.edo.account', string='Document Exchange', company_dependent=True,
        domain="[('company_id', '=', current_company_id), ('provider', '!=', False)]",
        help='How documents are exchanged with this counterparty (an EDO service or КЕП): '
             'proposed when a document is sent. Empty — the first EDO account of the company.')
