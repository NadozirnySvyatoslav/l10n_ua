import base64
import io
import logging

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MONO_INVOICE_URL = 'https://api.monobank.ua/api/merchant/invoice/create'
MONO_WEBHOOK_PATH = '/l10n_ua_mono_acquiring/webhook'


class MonoAcquiringMixin(models.AbstractModel):
    """Спільна логіка створення платіжного посилання Monobank Acquiring.

    Споживачі (sale.order, account.move) успадковують міксин і перевизначають
    суму/кошик/призначення платежу.
    """
    _name = 'l10n_ua.mono.acquiring.mixin'
    _description = 'Monobank Acquiring Mixin'

    mono_payment_link = fields.Char(
        string="Посилання Monobank",
        readonly=True,
        tracking=True,
    )
    mono_invoice_id = fields.Char(
        string="Monobank Invoice ID",
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # QR / journal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_qr_data_uri(value):
        """QR-код як data:image/svg+xml;base64 URI."""
        if not value:
            return False
        try:
            import qrcode
            import qrcode.image.svg
            qr = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
            buf = io.BytesIO()
            qr.save(buf)
            return ('data:image/svg+xml;base64,'
                    + base64.b64encode(buf.getvalue()).decode())
        except Exception:
            _logger.warning("QR code generation failed", exc_info=True)
            return False

    def _get_mono_qr_barcode_url(self):
        self.ensure_one()
        return self._make_qr_data_uri(self.mono_payment_link)

    def _get_mono_acquiring_journal(self):
        """Банківський журнал з налаштованим токеном Monobank Acquiring."""
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('mono_acquiring_token', '!=', False),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "Не знайдено банківський журнал з токеном Monobank Acquiring. "
                "Налаштуйте токен у Бухгалтерія → Налаштування → Журнали."))
        return journal

    # ------------------------------------------------------------------
    # Overridable per consumer
    # ------------------------------------------------------------------

    def _mono_amount(self):
        raise NotImplementedError

    def _mono_basket(self):
        return []

    def _mono_reference(self):
        self.ensure_one()
        return self.name or ''

    def _mono_destination(self):
        self.ensure_one()
        return _("Оплата %s") % (self.name or '')

    @staticmethod
    def _mono_basket_line(name, qty, subtotal, unit, code, icon):
        qty = qty or 1
        return {
            'name': name,
            'qty': qty,
            'sum': int(round(subtotal / qty * 100)),
            'unit': unit or 'шт.',
            'code': code,
            'icon': icon,
        }

    def _mono_product_icon(self, product):
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        return (f"{base_url}/web/image?model=product.template"
                f"&field=image_128&id={product.product_tmpl_id.id}")

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------

    def action_create_mono_link(self):
        """Створити рахунок Monobank Acquiring і зберегти посилання на оплату."""
        self.ensure_one()
        amount = self._mono_amount()
        if not amount or amount <= 0:
            raise UserError(_("Немає суми до оплати."))

        journal = self._get_mono_acquiring_journal()
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')

        payload = {
            'amount': int(round(amount * 100)),
            'ccy': 980,  # UAH
            'webHookUrl': f"{base_url}{MONO_WEBHOOK_PATH}",
            'merchantPaymInfo': {
                'reference': self._mono_reference(),
                'destination': self._mono_destination(),
                'basketOrder': self._mono_basket(),
            },
            'paymentType': 'debit',
        }

        resp = requests.post(
            MONO_INVOICE_URL,
            json=payload,
            headers={
                'X-Token': journal.mono_acquiring_token,
                'X-Cms': 'odoo',
                'X-Cms-Version': '19.0',
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise UserError(
                _("Monobank API помилка %s: %s") % (resp.status_code, resp.text))

        result = resp.json()
        self.write({
            'mono_payment_link': result.get('pageUrl'),
            'mono_invoice_id': result.get('invoiceId'),
        })
