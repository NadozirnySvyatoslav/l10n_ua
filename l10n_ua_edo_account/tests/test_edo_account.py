"""Міст ЕДО для рахунків (#81): надсилання з рахунку, статус на рахунку,
рахунок постачальника з вхідного документа. Провайдер підмінено."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestEdoAccount(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.edo = cls.env['l10n_ua.edo.account'].create({
            'name': 'ЕДО (тест)', 'company_id': cls.env.company.id, 'edrpou': '11111116'})
        cls.invoice = cls.init_invoice('out_invoice', products=cls.product_a, post=True)

    def setUp(self):
        super().setUp()
        self.calls = []
        test = self

        def fake_call(account, operation, *args):
            test.calls.append((operation, args))
            if operation == 'upload':
                return {'id': 'doc-1', 'status': 'uploaded'}
            if operation == 'normalize':
                data = args[0]
                return {'provider_ref': data['id'], 'state': data['status']}
            if operation == 'fetch':
                return [{'id': 'doc-1', 'status': 'sent'}]
            if operation == 'download':
                return 'bill.pdf', b'%PDF-1.4 bill'
            return None
        self.patch(type(self.env['l10n_ua.edo.account']), '_call', fake_call)

    def test_send_invoice(self):
        report = self.invoice._edo_reports()[:1]
        self.assertTrue(report)
        doc = self.invoice._edo_send(self.edo, report, '22222221', ['buh@example.com'])
        upload = next(args[0] for op, args in self.calls if op == 'upload')
        self.assertEqual(upload['number'], self.invoice.name)
        self.assertEqual(upload['amount'], self.invoice.amount_total)
        self.assertTrue(upload['content'])                            # the rendered report (HTML in tests)
        self.assertTrue(upload['filename'].endswith('.pdf'))
        self.assertFalse(upload['recipient_signs_first'])
        self.assertNotIn('send', [op for op, _a in self.calls])      # waits for our signature
        self.assertEqual((doc.res_model, doc.res_id), ('account.move', self.invoice.id))
        self.assertEqual(self.invoice.edo_document_count, 1)
        self.assertEqual(self.invoice.edo_state, 'uploaded')
        self.assertTrue(doc.attachment_id)

    def test_recipient_signs_first_sends_right_away(self):
        report = self.invoice._edo_reports()[:1]
        doc = self.invoice._edo_send(self.edo, report, '22222221', send=True)
        self.assertIn('send', [op for op, _a in self.calls])
        self.assertEqual(doc.state, 'sent')

    def test_wizard_defaults(self):
        wizard = self.env['l10n_ua.edo.send.wizard'].with_context(
            default_res_model='account.move', default_res_id=self.invoice.id).create({
                'account_id': self.edo.id})
        self.assertTrue(wizard.report_id)
        self.assertEqual(wizard.title, self.invoice.display_name)

    def test_vendor_bill_from_incoming_document(self):
        doc = self.env['l10n_ua.edo.document'].create({
            'name': 'Рахунок № 45', 'account_id': self.edo.id, 'direction': 'in',
            'provider_ref': 'in-45', 'number': '45', 'partner_id': self.partner_a.id,
            'date': '2026-10-20', 'state': 'sent'})
        action = doc.action_create_vendor_bill()
        bill = self.env['account.move'].browse(action['res_id'])
        self.assertEqual((bill.move_type, bill.partner_id, bill.ref), ('in_invoice', self.partner_a, '45'))
        self.assertEqual(doc._record(), bill)
        self.assertTrue(self.env['ir.attachment'].search(
            [('res_model', '=', 'account.move'), ('res_id', '=', bill.id), ('name', '=', 'bill.pdf')]))
        # Twice: opens the same bill
        self.assertEqual(doc.action_create_vendor_bill()['res_id'], bill.id)

    def test_category_from_the_rule(self):
        report = self.invoice._edo_reports()[:1]
        category = self.env['l10n_ua.edo.category'].create(
            {'account_id': self.edo.id, 'code': '2', 'name': 'Рахунок'})
        self.env['l10n_ua.edo.category.rule'].create(
            {'account_id': self.edo.id, 'report_id': report.id, 'category_id': category.id})
        wizard = self.env['l10n_ua.edo.send.wizard'].with_context(
            default_res_model='account.move', default_res_id=self.invoice.id).create({'account_id': self.edo.id})
        self.assertEqual(wizard.category_id, category)
        wizard.recipient_edrpou = '22222221'
        wizard.action_send()
        upload = next(args[0] for op, args in self.calls if op == 'upload')
        self.assertEqual(upload['category'], '2')

    def test_send_many(self):
        self.partner_a.email = 'buh@a.example.com'
        no_contacts = self.env['res.partner'].create({'name': 'Без реквізитів'})
        second = self.init_invoice('out_invoice', partner=no_contacts, products=self.product_a, post=True)
        invoices = self.invoice | second
        action = invoices.action_edo_send()
        self.assertEqual(action['context']['default_res_ids'], f'{self.invoice.id},{second.id}')
        wizard = self.env['l10n_ua.edo.send.wizard'].with_context(**action['context']).create(
            {'account_id': self.edo.id})
        self.assertEqual(wizard.record_count, 2)
        result = wizard.action_send()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('1', result['params']['message'])
        self.assertIn(second.display_name, result['params']['message'])
        self.assertEqual(self.invoice.edo_document_count, 1)
        self.assertEqual(second.edo_document_count, 0)
        upload = next(args[0] for op, args in self.calls if op == 'upload')
        self.assertEqual(upload['recipient_emails'], ['buh@a.example.com'])

    def test_no_vendor_bill_from_contract(self):
        """A contract that came in is not a bill: no button, and the action refuses."""
        if not hasattr(self.edo, '_vchasno_bill_categories'):
            self.skipTest('l10n_ua_edo_vchasno is not installed')
        self.edo.provider = 'vchasno'
        make = self.env['l10n_ua.edo.document'].create
        contract = make({'name': 'NDA', 'account_id': self.edo.id, 'direction': 'in',
                         'category': '3', 'partner_id': self.partner_a.id})
        invoice = make({'name': 'Рахунок', 'account_id': self.edo.id, 'direction': 'in',
                        'category': '2', 'partner_id': self.partner_a.id})
        unknown = make({'name': 'Інше', 'account_id': self.edo.id, 'direction': 'in',
                        'partner_id': self.partner_a.id})
        self.assertEqual((contract.can_create_bill, invoice.can_create_bill, unknown.can_create_bill),
                         (False, True, True))
        with self.assertRaises(UserError):
            contract.action_create_vendor_bill()
