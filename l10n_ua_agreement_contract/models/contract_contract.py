from odoo import fields, models


class ContractContract(models.Model):
    _inherit = 'contract.contract'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        ondelete='set null',
        copy=False,
        index='btree_not_null',
        help='The agreement the recurring invoices are issued under.',
    )
