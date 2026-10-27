from odoo import fields, models


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'l10n_ua.edo.mixin']

    def _edo_reports(self):
        """The Рахунок-фактура first: it is what the customer signs and pays."""
        reports = super()._edo_reports()
        rahunok = self.env.ref('l10n_ua_doc_reports.action_report_rahunok_sale', raise_if_not_found=False)
        return reports.sorted(lambda r: r != rahunok)

    def _edo_meta(self):
        meta = super()._edo_meta()
        meta.update({
            'number': self.name,
            'date': fields.Datetime.context_timestamp(self, self.date_order).date()
            if self.date_order else False,
            'amount': self.amount_total,
            'currency': self.currency_id.name,
        })
        return meta
