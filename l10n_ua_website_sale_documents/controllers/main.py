from odoo.http import content_disposition, request, route
from odoo.tools.pdf import merge_pdf

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleUaDocuments(WebsiteSale):

    @route()
    def print_saleorder(self, **kwargs):
        """Print after payment: the act / delivery note of the invoice, once there is one.

        The order is paid at this point, so a request for payment (the Рахунок-фактура) is no
        longer what the customer needs. With a posted customer invoice the primary document
        of its company is printed; until the invoice exists the core route prints the order.
        """
        order_id = request.session.get('sale_last_order_id')
        order_sudo = request.env['sale.order'].sudo().browse(order_id).exists() if order_id else None
        invoice = order_sudo and order_sudo._l10n_ua_printable_invoice()
        reports = invoice and invoice._l10n_ua_get_primary_doc_reports()
        if not reports:
            return super().print_saleorder(**kwargs)
        Report = request.env['ir.actions.report'].sudo()
        documents = [Report._render_qweb_pdf(report, invoice.ids)[0] for report in reports]
        pdf = documents[0] if len(documents) == 1 else merge_pdf(documents)
        filename = invoice._l10n_ua_get_primary_doc_filename(reports[:1])
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', content_disposition(filename, disposition_type='inline')),
        ])
