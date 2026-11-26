from odoo import fields, models


class L10nUaEdoCategory(models.Model):
    """A category of documents in the EDO service (Рахунок, Акт, Договір …)."""
    _name = 'l10n_ua.edo.category'
    _description = 'EDO Document Category'
    _order = 'account_id, name'

    account_id = fields.Many2one('l10n_ua.edo.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True)
    code = fields.Char(string='Code in the Service', required=True)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'UNIQUE(account_id, code)',
        'A category of the service is loaded only once per EDO account.',
    )


class L10nUaEdoCategoryRule(models.Model):
    """Which category a printed form is sent under."""
    _name = 'l10n_ua.edo.category.rule'
    _description = 'EDO Category of a Report'
    _order = 'account_id, report_id'

    account_id = fields.Many2one('l10n_ua.edo.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True)
    report_id = fields.Many2one(
        'ir.actions.report', string='Printed Form', required=True, ondelete='cascade',
        domain=[('report_type', '=', 'qweb-pdf')])
    category_id = fields.Many2one(
        'l10n_ua.edo.category', required=True, ondelete='cascade',
        domain="[('account_id', '=', account_id)]")

    _report_uniq = models.Constraint(
        'UNIQUE(account_id, report_id)',
        'A printed form has one category per EDO account.',
    )
