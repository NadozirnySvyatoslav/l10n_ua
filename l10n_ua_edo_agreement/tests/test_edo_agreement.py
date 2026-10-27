"""Міст ЕДО для договорів (#81): договір підписується через ЕДО.
Провайдер підмінено."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestEdoAgreement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.edo = cls.env['l10n_ua.edo.account'].create({'name': 'ЕДО (тест)', 'company_id': cls.env.company.id})
        cls.partner = cls.env['res.partner'].create({'name': 'ТОВ «Замовник»', 'is_company': True})
        cls.agreement = cls.env['l10n_ua.agreement'].create({
            'name': 'Договір поставки', 'partner_id': cls.partner.id, 'amount_total': 120000})

    def setUp(self):
        super().setUp()
        self.status = 'uploaded'
        test = self

        def fake_call(account, operation, *args):
            if operation == 'upload':
                return {'id': 'agr-1', 'status': 'uploaded'}
            if operation == 'normalize':
                return {'provider_ref': args[0]['id'], 'state': args[0]['status']}
            if operation == 'fetch':
                return [{'id': 'agr-1', 'status': test.status}]
            if operation == 'download':
                return 'dogovir_signed.zip', b'PK signed'
            return None
        self.patch(type(self.env['l10n_ua.edo.account']), '_call', fake_call)

    def test_agreement_signed_through_edo(self):
        report = self.agreement._edo_reports()[:1]
        self.assertEqual(report, self.env.ref('l10n_ua_agreement.action_report_agreement'))
        doc = self.agreement._edo_send(self.edo, report, '22222221')
        self.assertEqual(doc.number, self.agreement.code)
        self.assertIn(self.agreement.code, doc.name)
        self.assertEqual(self.agreement.state, 'draft')

        self.status = 'sent'
        doc.action_refresh()
        self.assertEqual(self.agreement.state, 'to_sign')

        self.status = 'signed'
        doc.action_refresh()
        self.assertEqual(self.agreement.state, 'signed')
        self.assertTrue(self.agreement.signature_date)
        self.assertEqual(self.agreement.signed_filename, 'dogovir_signed.zip')
        self.assertTrue(self.agreement.signed_document)

    def test_cancelled_agreement_is_left_alone(self):
        doc = self.agreement._edo_send(self.edo, self.agreement._edo_reports()[:1], '22222221')
        self.agreement.action_cancel()
        self.status = 'signed'
        doc.action_refresh()
        self.assertEqual(self.agreement.state, 'cancelled')
