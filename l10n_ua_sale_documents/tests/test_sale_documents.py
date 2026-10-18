"""Українські документи в листах продажу. Усі дані в тестах вигадані."""
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account_payment.tests.common import AccountPaymentCommon
from odoo.addons.mail.tests.common import MailCase
from odoo.addons.sale.tests.common import SaleCommon

ORDER_TEMPLATES = (
    'sale.email_template_edi_sale',
    'sale.mail_template_sale_confirmation',
    'sale.mail_template_sale_payment_executed',
)
ACT = 'l10n_ua_doc_reports.report_act_document'
VYDATKOVA = 'l10n_ua_doc_reports.report_vydatkova_document'


@tagged('post_install', '-at_install', 'l10n_ua_sale_documents')
class TestSaleDocuments(AccountPaymentCommon, MailCase, SaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.sale_order.currency_id
        cls.partner = cls.sale_order.partner_invoice_id
        cls.partner.email = 'customer@example.com'
        cls.provider.journal_id.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_provider_id == cls.provider
        ).payment_account_id = cls.inbound_payment_method_line.payment_account_id
        cls.service_order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'require_payment': True,
            'order_line': [Command.create({
                'product_id': cls.service_product.id,
                'product_uom_qty': 2,
            })],
        })

    # Helpers

    def _attachment_names(self, template, order):
        values = template._generate_template(order.ids, ('attachment_ids', 'report_template_ids'))
        return [name for name, _content in values[order.id].get('attachments', [])]

    def _invoice(self, products):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [Command.create({
                'product_id': product.id, 'quantity': 1, 'price_unit': 100, 'tax_ids': False,
            }) for product in products],
        })
        invoice.action_post()
        return invoice

    def _dynamic_reports(self, invoice):
        widget = self.env['account.move.send']._get_default_mail_attachments_widget(
            invoice, invoice._get_mail_template())
        return [a['dynamic_report'] for a in widget if a.get('dynamic_report')]

    # Order e-mails

    def test_order_mails_attach_rahunok(self):
        """Пропозиція, підтвердження й лист про оплату містять Рахунок-фактуру, а не PDF Odoo."""
        for xmlid in ORDER_TEMPLATES:
            names = self._attachment_names(self.env.ref(xmlid), self.sale_order)
            self.assertEqual(len(names), 1, xmlid)
            self.assertTrue(names[0].startswith('Рахунок-фактура_%s.' % self.sale_order.name),
                            (xmlid, names))

    def test_order_mail_standard_when_disabled(self):
        """Вимкнено в компанії — стандартний PDF замовлення Odoo."""
        self.env.company.l10n_ua_sale_rahunok_in_mail = False
        names = self._attachment_names(self.env.ref('sale.email_template_edi_sale'), self.sale_order)
        self.assertEqual(len(names), 1)
        self.assertFalse(names[0].startswith('Рахунок-фактура'), names)

    def test_site_order_report_is_rahunok(self):
        """Кнопка «Друк» після оплати (/shop/print) і PDF замовлення в кабінеті клієнта
        викликають звіт замовлення Odoo — компанія з увімкненою опцією отримує Рахунок-фактуру."""
        Report = self.env['ir.actions.report']
        for xmlid in ('sale.action_report_saleorder', 'sale.action_report_pro_forma_invoice'):
            html = Report._render_qweb_html(xmlid, self.sale_order.ids)[0].decode()
            self.assertIn('Рахунок-фактура', html, xmlid)
        self.assertEqual(
            Report._l10n_ua_order_report_ref('sale.action_report_saleorder', self.sale_order.ids),
            self.env.ref('l10n_ua_doc_reports.action_report_rahunok_sale'))

    def test_site_order_report_standard_when_disabled(self):
        """Вимкнено в компанії — звіт замовлення Odoo як є."""
        self.env.company.l10n_ua_sale_rahunok_in_mail = False
        html = self.env['ir.actions.report']._render_qweb_html(
            'sale.action_report_saleorder', self.sale_order.ids)[0].decode()
        self.assertNotIn('Рахунок-фактура', html)

    def test_other_reports_not_swapped(self):
        """Інші звіти не підміняються."""
        Report = self.env['ir.actions.report']
        invoice = self._invoice(self.service_product)
        self.assertEqual(Report._l10n_ua_order_report_ref('account.account_invoices', invoice.ids),
                         'account.account_invoices')

    def test_core_templates_untouched(self):
        """Шаблони листів Odoo не змінюються: видалення модуля повертає стандартну поведінку
        без жодного uninstall_hook."""
        core_report = self.env.ref('sale.action_report_saleorder')
        for xmlid in ORDER_TEMPLATES:
            self.assertEqual(self.env.ref(xmlid).report_template_ids, core_report, xmlid)

    def test_confirmation_mail_message(self):
        """Підтвердження замовлення, надіслане клієнту, несе Рахунок-фактуру."""
        with self.mock_mail_gateway():
            self.service_order.with_context(send_email=True).action_confirm()
        names = self.service_order.message_ids.attachment_ids.mapped('name')
        self.assertTrue(any(n.startswith('Рахунок-фактура_') for n in names), names)
        self.assertFalse(any(n.startswith(('Order', 'Quotation')) for n in names), names)

    # Invoice e-mails

    def test_invoice_mail_act_default(self):
        self.assertEqual(self.env.company.l10n_ua_invoice_primary_doc, 'act')
        invoice = self._invoice(self.product)
        self.assertEqual(self._dynamic_reports(invoice), [ACT])

    def test_invoice_mail_vydatkova(self):
        self.env.company.l10n_ua_invoice_primary_doc = 'vydatkova'
        invoice = self._invoice(self.service_product)
        self.assertEqual(self._dynamic_reports(invoice), [VYDATKOVA])

    def test_invoice_mail_none(self):
        self.env.company.l10n_ua_invoice_primary_doc = 'none'
        self.assertEqual(self._dynamic_reports(self._invoice(self.service_product)), [])

    def test_invoice_mail_auto(self):
        """«За складом рахунку»: послуги — акт, товари — накладна, змішаний — обидва."""
        self.env.company.l10n_ua_invoice_primary_doc = 'auto'
        self.assertEqual(self._dynamic_reports(self._invoice(self.service_product)), [ACT])
        self.assertEqual(self._dynamic_reports(self._invoice(self.product)), [VYDATKOVA])
        self.assertEqual(
            self._dynamic_reports(self._invoice(self.product + self.service_product)),
            [ACT, VYDATKOVA])

    def test_invoice_mail_keeps_invoice_pdf(self):
        """Акт додається поруч із PDF рахунку Odoo, а не замість нього; кредит-нота — без акта."""
        invoice = self._invoice(self.service_product)
        with self.mock_mail_gateway():
            self.env['account.move.send']._generate_and_send_invoices(
                invoice, sending_methods=['email'])
        self.assertTrue(invoice.invoice_pdf_report_id)
        names = invoice.message_ids.attachment_ids.mapped('name')
        self.assertIn(invoice.invoice_pdf_report_id.name, names)
        self.assertIn('Акт_%s.pdf' % invoice.name.replace('/', '_'), names)

        refund = invoice._reverse_moves()
        refund.action_post()
        self.assertEqual(self._dynamic_reports(refund), [])

    def test_invoice_mail_no_act_for_down_payment(self):
        """Рахунок на передоплату нічого не передає: акта до нього немає."""
        self.sale_order.action_confirm()
        wizard = self.env['sale.advance.payment.inv'].with_context(
            active_model='sale.order', active_ids=self.sale_order.ids,
        ).create({'advance_payment_method': 'percentage', 'amount': 50})
        wizard.create_invoices()
        invoice = self.sale_order.invoice_ids
        invoice.action_post()
        self.assertTrue(invoice.invoice_line_ids.filtered('is_downpayment'))
        self.assertEqual(self._dynamic_reports(invoice), [])

    # Automatic invoicing after an online payment

    def _pay(self, order, provider_state):
        self.env['ir.config_parameter'].sudo().set_param('sale.automatic_invoice', 'True')
        self.provider.state = provider_state
        self.amount = order.amount_total
        tx = self._create_transaction(flow='redirect', sale_order_ids=[order.id], state='done')
        with (
            mute_logger('odoo.addons.sale.models.payment_transaction'),
            self.mock_mail_gateway(),
        ):
            tx._post_process()
        return tx

    def test_auto_invoice_enabled_provider(self):
        """Оплата через робочий провайдер: рахунок створено, проведено й надіслано з актом."""
        tx = self._pay(self.service_order, 'enabled')
        self.assertEqual(self.service_order.state, 'sale')
        invoice = tx.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.state, 'posted')
        self.assertTrue(invoice.is_move_sent)
        names = invoice.message_ids.attachment_ids.mapped('name')
        self.assertIn('Акт_%s.pdf' % invoice.name.replace('/', '_'), names)
        order_names = self.service_order.message_ids.attachment_ids.mapped('name')
        self.assertTrue(any(n.startswith('Рахунок-фактура_') for n in order_names), order_names)

    def test_auto_invoice_skipped_for_test_provider(self):
        """Тестова оплата не створює рахунку (доходу в книзі), але замовлення підтверджено
        і решта обробки транзакції виконана."""
        tx = self._pay(self.service_order, 'test')
        self.assertEqual(self.service_order.state, 'sale')
        self.assertFalse(tx.invoice_ids)
        self.assertFalse(self.service_order.invoice_ids)
        self.assertTrue(tx.is_post_processed)
