"""Взаєморозрахунки у розрізі договорів (#208)."""

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgreementAccount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Клієнт', 'is_company': True})
        cls.agreement = cls.env['l10n_ua.agreement'].create({
            'code': 'AGR-1', 'name': 'Договір №1',
            'partner_id': cls.partner.id, 'company_id': cls.company.id})
        cls.product = cls.env['product.product'].create({
            'name': 'Послуга', 'type': 'service', 'list_price': 1000.0})

    def _invoice(self, agreement=None):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'l10n_ua_agreement_id': agreement.id if agreement else False,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1, 'price_unit': 1000.0})],
        })

    def test_move_line_related_agreement(self):
        inv = self._invoice(self.agreement)
        self.assertEqual(inv.l10n_ua_agreement_id, self.agreement)
        # Related stored поле проброшене в усі рядки проводки
        self.assertTrue(inv.line_ids)
        for line in inv.line_ids:
            self.assertEqual(line.l10n_ua_agreement_id, self.agreement)

    def test_prepare_invoice_propagates(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'l10n_ua_agreement_id': self.agreement.id,
        })
        vals = so._prepare_invoice()
        self.assertEqual(vals.get('l10n_ua_agreement_id'), self.agreement.id)

    def test_payment_register_sets_agreement(self):
        inv = self._invoice(self.agreement)
        inv.action_post()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids).create({})
        payments = wiz._create_payments()
        self.assertEqual(payments.l10n_ua_agreement_id, self.agreement)

    def test_payment_register_mixed_agreements_left_empty(self):
        other = self.env['l10n_ua.agreement'].create({
            'code': 'AGR-2', 'name': 'Договір №2',
            'partner_id': self.partner.id, 'company_id': self.company.id})
        inv1 = self._invoice(self.agreement)
        inv2 = self._invoice(other)
        (inv1 | inv2).action_post()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=(inv1 | inv2).ids).create({
                'group_payment': True})
        payments = wiz._create_payments()
        # Різні договори — договір на платежі не проставляється
        self.assertFalse(payments.l10n_ua_agreement_id)

    def test_recon_wizard_domain(self):
        wiz = self.env['l10n_ua.reconciliation.act.wizard'].create({
            'partner_id': self.partner.id,
            'l10n_ua_agreement_id': self.agreement.id,
            'date_from': fields.Date.to_date('2025-01-01'),
            'date_to': fields.Date.to_date('2025-12-31'),
        })
        domain = wiz._get_move_line_domain()
        self.assertIn(('l10n_ua_agreement_id', '=', self.agreement.id), domain)
