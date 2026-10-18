"""Кнопка «Друк» після оплати. Усі дані в тестах вигадані."""
from urllib.parse import unquote

from odoo import http
from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged('post_install', '-at_install', 'l10n_ua_website_sale_documents')
class TestShopPrint(HttpCase, SaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [Command.create({'product_id': cls.service_product.id, 'product_uom_qty': 1})],
        })
        cls.order.action_confirm()

    def _print(self):
        session = self.authenticate(None, None)
        session['sale_last_order_id'] = self.order.id
        http.root.session_store.save(session)
        response = self.url_open('/shop/print')
        self.assertEqual(response.status_code, 200)
        return response

    def test_paid_order_with_invoice_prints_act(self):
        """Оплачене замовлення з проведеним рахунком — друкується акт рахунку."""
        invoice = self.order._create_invoices()
        invoice.action_post()
        response = self._print()
        self.assertIn('Акт_%s' % invoice.name.replace('/', '_'),
                      unquote(response.headers.get('Content-Disposition', '')))

    def test_vydatkova_when_company_chooses_it(self):
        self.env.company.l10n_ua_invoice_primary_doc = 'vydatkova'
        invoice = self.order._create_invoices()
        invoice.action_post()
        response = self._print()
        self.assertIn('Видаткова_накладна', unquote(response.headers.get('Content-Disposition', '')))

    def test_without_invoice_prints_order(self):
        """Рахунку ще немає (наприклад, тестова оплата) — друкується замовлення."""
        response = self._print()
        self.assertNotIn('Акт_', unquote(response.headers.get('Content-Disposition', '')))
        self.assertIn('Рахунок-фактура', response.text)

    def test_draft_invoice_ignored(self):
        self.order._create_invoices()
        self.assertFalse(self.order._l10n_ua_printable_invoice())
