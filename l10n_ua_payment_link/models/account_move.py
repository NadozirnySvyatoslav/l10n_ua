import base64
import io
import logging

from base64 import urlsafe_b64encode

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    nbu_payment_link = fields.Char(
        string="Посилання для оплати (НБУ QR)",
        compute='_compute_nbu_payment_link',
    )

    @api.depends('amount_residual', 'company_id', 'name', 'invoice_date')
    def _compute_nbu_payment_link(self):
        template_raw = (
            self.env['ir.config_parameter']
            .sudo()
            .get_str('l10n_ua.nbu_qr_template', '')
        )
        template = template_raw.replace('\\n', '\n').replace('\\r', '\r')
        for move in self:
            link = False
            if (
                template
                and move.move_type == 'out_invoice'
                and move.amount_residual > 0
            ):
                company_partner = move.company_id.partner_id
                bank = company_partner.bank_ids[:1]
                if bank:
                    try:
                        data = template.format(
                            name=company_partner.name or '',
                            account=bank.sanitized_acc_number or bank.acc_number or '',
                            currency='UAH',
                            amount=move.amount_residual,
                            edrpou=company_partner.edrpou or '',
                            number=move.name or '',
                            date=move.invoice_date or '',
                        )
                        encoded = urlsafe_b64encode(data.encode('utf-8')).decode('utf-8')
                        link = f"https://bank.gov.ua/qr/{encoded}"
                    except Exception:
                        _logger.warning(
                            "NBU QR link build failed for %s", move.name, exc_info=True
                        )
            move.nbu_payment_link = link

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

    def _get_nbu_qr_barcode_url(self, width=200, height=200):
        self.ensure_one()
        return self._make_qr_data_uri(self.nbu_payment_link)
