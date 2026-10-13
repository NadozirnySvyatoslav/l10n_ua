from odoo import api, fields, models

from odoo.addons.l10n_ua_account_base.tools.formatters import amount_to_words_ua


class SaleOrder(models.Model):
    _inherit = ['sale.order', 'l10n_ua.doc.report.mixin']

    l10n_ua_amount_words = fields.Char(
        string='Amount in Words (UA)',
        compute='_compute_l10n_ua_amount_words',
    )

    @api.depends('amount_total', 'currency_id')
    def _compute_l10n_ua_amount_words(self):
        for order in self:
            if order.currency_id and order.currency_id.name == 'UAH':
                order.l10n_ua_amount_words = amount_to_words_ua(
                    order.amount_total, currency='UAH',
                )
            else:
                order.l10n_ua_amount_words = ''

    def _get_ua_report_lines(self):
        """Return product lines only: no sections, subsections or notes."""
        return self.order_line.filtered(lambda l: not l.display_type)

    def _get_ua_doc_date(self):
        """Order date in the user's timezone."""
        return fields.Datetime.context_timestamp(self, self.date_order).date()

    def _get_ua_line_qty(self, line):
        return line.product_uom_qty

    def _get_ua_note(self):
        return self.note

    def _get_ua_validity_note(self):
        if self.validity_date:
            return 'Рахунок дійсний до %s.' % self._get_ua_date_short(self.validity_date)
        return 'Рахунок дійсний до оплати протягом 3 банківських днів.'
