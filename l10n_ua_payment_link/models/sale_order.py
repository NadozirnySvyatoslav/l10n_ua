import base64
import io
import logging

from base64 import urlsafe_b64encode

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nbu_payment_link = fields.Char(
        string="Посилання для оплати (НБУ QR)",
        compute='_compute_nbu_payment_link',
    )

    @api.depends('amount_total', 'company_id', 'name', 'date_order')
    def _compute_nbu_payment_link(self):
        template_raw = (
            self.env['ir.config_parameter']
            .sudo()
            .get_str('l10n_ua.nbu_qr_template', '')
        )
        template = template_raw.replace('\\n', '\n').replace('\\r', '\r')
        for order in self:
            link = False
            if template and order.amount_total:
                company_partner = order.company_id.partner_id
                bank = company_partner.bank_ids[:1]
                if bank:
                    try:
                        data = template.format(
                            name=company_partner.name or '',
                            account=bank.sanitized_account_number or bank.account_number or '',
                            currency='UAH',
                            amount=order.amount_total,
                            edrpou=company_partner.edrpou or '',
                            number=order.name or '',
                            date=order.date_order.date() if order.date_order else '',
                        )
                        encoded = urlsafe_b64encode(data.encode('utf-8')).decode('utf-8')
                        link = f"https://bank.gov.ua/qr/{encoded}"
                    except Exception:
                        _logger.warning("NBU QR link build failed for %s", order.name, exc_info=True)
            order.nbu_payment_link = link

    @staticmethod
    def _make_qr_data_uri(value):
        """Generate QR code as data:image/svg+xml;base64 URI."""
        if not value:
            return False
        try:
            import qrcode
            import qrcode.image.svg
            qr = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
            buf = io.BytesIO()
            qr.save(buf)
            return 'data:image/svg+xml;base64,' + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            _logger.warning("QR code generation failed", exc_info=True)
            return False

    def _get_nbu_qr_barcode_url(self, width=300, height=300):
        self.ensure_one()
        return self._make_qr_data_uri(self.nbu_payment_link)
