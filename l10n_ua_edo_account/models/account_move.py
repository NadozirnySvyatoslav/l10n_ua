from odoo import models


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'l10n_ua.edo.mixin']

    def _edo_reports(self):
        """The Ukrainian forms first (Акт, Видаткова, Рахунок-фактура), then the rest."""
        reports = super()._edo_reports()
        xmlids = reports.get_external_id()
        return reports.sorted(lambda r: (not (xmlids.get(r.id) or '').startswith('l10n_ua'), r.name))

    def _edo_meta(self):
        meta = super()._edo_meta()
        meta.update({
            'number': self.name if self.name and self.name != '/' else False,
            'date': self.invoice_date or self.date,
            'amount': self.amount_total,
            'currency': self.currency_id.name,
        })
        return meta
