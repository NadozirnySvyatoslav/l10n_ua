from odoo import fields, models

PRIMARY_DOC_SELECTION = [
    ('act', 'Service Act (Акт)'),
    ('vydatkova', 'Delivery Note (Видаткова накладна)'),
    ('auto', 'By Invoice Content'),
    ('none', 'Do Not Attach'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_sale_rahunok_in_mail = fields.Boolean(
        string='Рахунок-фактура in Order E-mails',
        default=True,
        help='Quotation, order confirmation and payment e-mails attach the Ukrainian '
             'Рахунок-фактура instead of the standard Odoo order PDF.',
    )
    l10n_ua_invoice_primary_doc = fields.Selection(
        selection=PRIMARY_DOC_SELECTION,
        string='Primary Document in Invoice E-mails',
        default='act',
        required=True,
        help='Document attached to customer invoice e-mails next to the Odoo invoice PDF. '
             'By invoice content: services only - service act, goods only - delivery note, '
             'services and goods - both documents.',
    )
