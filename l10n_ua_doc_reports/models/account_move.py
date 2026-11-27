from odoo import models


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'l10n_ua.doc.report.mixin']

    def _get_ua_report_lines(self):
        """Return product lines only: no sections, subsections or notes."""
        return self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _get_ua_doc_date(self):
        """Document date: invoice date, for drafts without it the accounting date."""
        return self.invoice_date or self.date

    def _get_ua_line_qty(self, line):
        return line.quantity

    def _get_ua_buyer(self):
        return self.commercial_partner_id

    def _get_ua_partner_bank(self):
        return self.partner_bank_id

    def _get_ua_due_date(self):
        return self.invoice_date_due

    def _get_ua_note(self):
        return self.narration

    def _get_ua_discount_total(self):
        return self.l10n_ua_discount_total
