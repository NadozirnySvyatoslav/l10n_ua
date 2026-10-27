"""Міст ЕДО для замовлень продажу (#81). Провайдер підмінено."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestEdoSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.edo = cls.env['l10n_ua.edo.account'].create({'name': 'ЕДО (тест)', 'company_id': cls.env.company.id})
        partner = cls.env['res.partner'].create({'name': 'ТОВ «Покупець»', 'is_company': True})
        product = cls.env['product.product'].create({'name': 'Послуга', 'type': 'service', 'list_price': 1500})
        cls.order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 2, 'price_unit': 1500})],
        })

    def setUp(self):
        super().setUp()
        self.calls = []
        test = self

        def fake_call(account, operation, *args):
            test.calls.append((operation, args))
            if operation == 'upload':
                return {'id': 'so-1', 'status': 'uploaded'}
            if operation == 'normalize':
                return {'provider_ref': args[0]['id'], 'state': args[0]['status']}
            return None
        self.patch(type(self.env['l10n_ua.edo.account']), '_call', fake_call)

    def test_send_order(self):
        reports = self.order._edo_reports()
        self.assertTrue(reports)
        rahunok = self.env.ref('l10n_ua_doc_reports.action_report_rahunok_sale', raise_if_not_found=False)
        if rahunok:
            self.assertEqual(reports[:1], rahunok)
        doc = self.order._edo_send(self.edo, reports[:1], '22222221')
        upload = next(args[0] for op, args in self.calls if op == 'upload')
        self.assertEqual((upload['number'], upload['amount']), (self.order.name, self.order.amount_total))
        self.assertTrue(upload['date'])
        self.assertEqual((doc.res_model, doc.res_id), ('sale.order', self.order.id))
        self.assertEqual(self.order.edo_state, 'uploaded')
