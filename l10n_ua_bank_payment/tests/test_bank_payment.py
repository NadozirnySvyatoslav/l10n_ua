"""Тести вихідних платіжних доручень із КЕП-підписом (#199)."""

import base64

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestBankPayment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env['res.partner'].create({'name': 'Payer'})
        cls.payer = cls.env['res.partner.bank'].create({
            'account_number': '26001234567890', 'partner_id': partner.id})

    def _payment(self, lines=None):
        pay = self.env['l10n_ua.bank.payment'].create({
            'payer_account_id': self.payer.id,
        })
        for vals in (lines or [{
            'recipient_name': 'ТОВ Постачальник',
            'recipient_edrpou': '12345678',
            'recipient_iban': 'UA113052990000026007891234567',
            'amount': 1500.50,
            'purpose': 'оплата за товар',
        }]):
            self.env['l10n_ua.bank.payment.line'].create(
                dict(vals, payment_id=pay.id))
        return pay

    def test_sequence_and_total(self):
        pay = self._payment()
        self.assertTrue(pay.name.startswith('ПЛ/'))
        self.assertAlmostEqual(pay.total_amount, 1500.50, places=2)

    def test_generate_file(self):
        pay = self._payment()
        pay.action_generate_file()
        self.assertEqual(pay.state, 'generated')
        self.assertTrue(pay.file_name.endswith('.xml'))
        root = etree.fromstring(pay.file_data.content)
        self.assertEqual(root.tag, 'PaymentOrder')
        self.assertEqual(root.get('count'), '1')
        p = root.find('Payment')
        self.assertEqual(p.findtext('Amount'), '1500.50')
        self.assertEqual(p.findtext('Account'),
                         'UA113052990000026007891234567')

    def test_action_kep_sign_returns_dialog(self):
        pay = self._payment()
        action = pay.action_kep_sign()
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params']['res_id'], pay.id)

    def test_prepare_signing_autogenerates(self):
        pay = self._payment()
        # Ще не сформовано файл — kep_prepare_signing формує його сам.
        payload = pay.kep_prepare_signing()
        self.assertEqual(pay.state, 'generated')
        docs = payload['documents']
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['name'], 'payment')
        self.assertEqual(docs[0]['format'], 'cades')
        # data_b64 декодується у валідний XML.
        xml = base64.b64decode(docs[0]['data_b64'])
        self.assertEqual(etree.fromstring(xml).tag, 'PaymentOrder')

    def test_submit_signed_sets_state(self):
        pay = self._payment()
        pay.action_generate_file()
        sig = base64.b64encode(b'signature-bytes').decode()
        res = pay.kep_submit_signed({'payment': sig})
        self.assertTrue(res['ok'])
        self.assertEqual(pay.state, 'signed')
        # Підпис збережено: Binary у Odoo 20 віддає сирі байти,
        # base64 — через to_base64().
        self.assertEqual(pay.signature_data.to_base64(), sig)

    def test_submit_without_signature_raises(self):
        pay = self._payment()
        pay.action_generate_file()
        with self.assertRaises(UserError):
            pay.kep_submit_signed({})

    def test_mark_sent_requires_signed(self):
        pay = self._payment()
        pay.action_generate_file()
        with self.assertRaises(UserError):
            pay.action_mark_sent()
        pay.kep_submit_signed({'payment': base64.b64encode(b'sig').decode()})
        pay.action_mark_sent()
        self.assertEqual(pay.state, 'sent')

    def test_generate_validates(self):
        pay = self.env['l10n_ua.bank.payment'].create({
            'payer_account_id': self.payer.id})
        # Без рядків — помилка.
        with self.assertRaises(UserError):
            pay.action_generate_file()
