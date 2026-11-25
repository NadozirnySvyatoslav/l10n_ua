from odoo import fields, models

DIRECTIONS = [('sale', 'With a Customer'), ('purchase', 'With a Vendor')]


class L10nUaAgreementType(models.Model):
    _name = 'l10n_ua.agreement.type'
    _description = 'Agreement Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    direction = fields.Selection(DIRECTIONS, required=True, default='sale')
    subject_template = fields.Html(
        string='Subject Template',
        translate=True,
        help='Text put into the subject of a new agreement of this type; '
             'edit it in the agreement as needed.',
    )
