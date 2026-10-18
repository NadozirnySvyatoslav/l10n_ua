from odoo import fields, models

from .res_company import PRIMARY_DOC_SELECTION


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_ua_sale_rahunok_in_mail = fields.Boolean(
        related='company_id.l10n_ua_sale_rahunok_in_mail',
        readonly=False,
    )
    l10n_ua_invoice_primary_doc = fields.Selection(
        selection=PRIMARY_DOC_SELECTION,
        related='company_id.l10n_ua_invoice_primary_doc',
        readonly=False,
    )
