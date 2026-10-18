from odoo import api, models
from odoo.tools.safe_eval import safe_eval, time

# Order reports of Odoo replaced by the Рахунок-фактура for companies that enable it
CORE_ORDER_REPORTS = (
    'sale.action_report_saleorder',
    'sale.action_report_pro_forma_invoice',
)
RAHUNOK_SALE_REPORT = 'l10n_ua_doc_reports.action_report_rahunok_sale'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _l10n_ua_eval_report_name(self, report, record):
        """File name of `report` for `record`, without extension (as mail templates do)."""
        if report.print_report_name:
            return safe_eval(report.print_report_name, {'object': record, 'time': time})
        return report.name

    @api.model
    def _l10n_ua_order_report_ref(self, report_ref, res_ids):
        """The Рахунок-фактура instead of the Odoo quotation / order report when every order
        printed belongs to a company that enabled it; `report_ref` unchanged otherwise.

        Odoo hard-codes its order report in the website: the Print button after payment
        (/shop/print), the PDF of the order in the customer portal and the copy posted on
        signature. Swapping it here gives the customer the same document everywhere.
        """
        if not res_ids:
            return report_ref
        report = self._get_report(report_ref)
        if report.model != 'sale.order' or report.get_external_id().get(report.id) not in CORE_ORDER_REPORTS:
            return report_ref
        rahunok = self.env.ref(RAHUNOK_SALE_REPORT, raise_if_not_found=False)
        if not rahunok:
            return report_ref
        ids = [res_ids] if isinstance(res_ids, int) else res_ids
        orders = self.env['sale.order'].sudo().browse(ids).exists()
        if not orders or not all(orders.company_id.mapped('l10n_ua_sale_rahunok_in_mail')):
            return report_ref
        return rahunok

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        report_ref = self._l10n_ua_order_report_ref(report_ref, res_ids)
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    def _render_qweb_html(self, report_ref, docids, data=None):
        report_ref = self._l10n_ua_order_report_ref(report_ref, docids)
        return super()._render_qweb_html(report_ref, docids, data=data)
