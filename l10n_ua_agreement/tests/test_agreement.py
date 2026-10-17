import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_agreement.models.agreement import L10nUaAgreement


@tagged('post_install', '-at_install')
class TestAgreement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Agreement = cls.env['l10n_ua.agreement']
        cls.partner = cls.env['res.partner'].create({'name': 'ТОВ Клієнт', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Іван Петренко', 'parent_id': cls.partner.id})
        cls.services = cls.env.ref('l10n_ua_agreement.agreement_type_services')
        cls.purchase_type = cls.env.ref('l10n_ua_agreement.agreement_type_purchase')

    def _agreement(self, **vals):
        return self.Agreement.create({
            'name': 'Супровід Odoo', 'partner_id': self.partner.id, **vals})

    def test_number_from_sequence(self):
        first, second = self._agreement(), self._agreement()
        self.assertNotEqual(first.code, '/')
        self.assertNotEqual(first.code, second.code)
        manual = self._agreement(code='15-Д')
        self.assertEqual(manual.code, '15-Д')

    def test_number_unique_per_partner(self):
        self._agreement(code='1')
        other = self.env['res.partner'].create({'name': 'ФОП Інший'})
        self._agreement(code='1', partner_id=other.id)
        with self.assertRaises(Exception), self.cr.savepoint():
            self._agreement(code='1')

    def test_direction_and_subject_from_type(self):
        self.services.subject_template = '<p>Надання послуг</p>'
        agreement = self._agreement(agreement_type_id=self.services.id)
        self.assertEqual(agreement.direction, 'sale')
        self.assertIn('Надання послуг', str(agreement.subject))
        purchase = self._agreement(agreement_type_id=self.purchase_type.id)
        self.assertEqual(purchase.direction, 'purchase')

    def test_display_name_and_search(self):
        agreement = self._agreement(code='77', start_date='2026-10-01')
        self.assertIn('77', agreement.display_name)
        self.assertIn('Супровід Odoo', agreement.display_name)
        found = self.Agreement.browse([rid for rid, _name in self.Agreement.name_search('77')])
        self.assertIn(agreement, found)

    def test_states_and_expiry(self):
        agreement = self._agreement(end_date=fields.Date.today() - timedelta(days=1))
        agreement.action_to_sign()
        self.assertEqual(agreement.state, 'to_sign')
        agreement.action_mark_signed()
        self.assertEqual(agreement.state, 'signed')
        self.assertEqual(agreement.signature_date, fields.Date.today())
        current = self._agreement(end_date=fields.Date.today() + timedelta(days=30))
        current.action_mark_signed()
        self.Agreement._cron_expire()
        self.assertEqual(agreement.state, 'expired')
        self.assertEqual(current.state, 'signed')

    def test_amendment(self):
        main = self._agreement(amount_total=1000)
        main.action_mark_signed()
        ctx = main.action_add_amendment()['context']
        amendment = self.Agreement.with_context(ctx).create({'name': 'Зміна ціни'})
        self.assertEqual(amendment.parent_id, main)
        self.assertTrue(amendment.is_amendment)
        self.assertEqual(amendment.partner_id, self.partner)
        self.assertEqual(main.amendment_count, 1)

    def test_kep_signature_stored(self):
        agreement = self._agreement()
        with patch.object(L10nUaAgreement, '_agreement_pdf', lambda self: b'%PDF-1.4 test'):
            action = agreement.action_sign_kep()
            self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
            spec = agreement.kep_prepare_signing()
        doc = spec['documents'][0]
        self.assertEqual(doc['format'], 'cades')
        self.assertEqual(base64.b64decode(doc['data_b64']), b'%PDF-1.4 test')
        signature = base64.b64encode(b'P7S-SIGNATURE').decode()
        agreement.kep_submit_signed({doc['name']: signature})
        self.assertEqual(agreement.state, 'to_sign')
        self.assertEqual(base64.b64decode(agreement.kep_signature), b'P7S-SIGNATURE')
        self.assertTrue(agreement.kep_signature_filename.endswith('.pdf.p7s'))
        self.assertEqual(agreement.kep_signed_by_id, self.env.user)
        with self.assertRaises(UserError):
            agreement.kep_submit_signed({})
        agreement.action_mark_signed()
        with self.assertRaises(UserError):
            agreement.action_sign_kep()

    def test_sale_order_and_partner_counters(self):
        agreement = self._agreement()
        agreement.action_mark_signed()
        order = self.env['sale.order'].create({
            'partner_id': self.contact.id, 'l10n_ua_agreement_id': agreement.id})
        self.assertEqual(order.l10n_ua_commercial_partner_id, self.partner)
        self.assertEqual(agreement.sale_order_count, 1)
        self.assertEqual(self.contact.l10n_ua_agreement_count, 1)
        self.assertEqual(self.partner.l10n_ua_agreement_count, 1)
        action = agreement.action_view_sale_orders()
        self.assertEqual(action['domain'], [('l10n_ua_agreement_id', '=', agreement.id)])

    def test_report_renders(self):
        agreement = self._agreement(amount_total=500, subject='<p>Предмет</p>')
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_agreement.action_report_agreement', agreement.ids)
        self.assertIn('Договір', html.decode())
        self.assertIn('ТОВ Клієнт', html.decode())
        purchase = self._agreement(direction='purchase')
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_agreement.action_report_agreement', purchase.ids)
        text = html.decode()
        # Договір з постачальником: контрагент — виконавець
        self.assertLess(text.index('ТОВ Клієнт'), text.index('«Виконавець»'))
