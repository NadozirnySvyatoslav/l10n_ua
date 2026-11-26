"""Договір у взаємозаліку (#371)."""

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'l10n_ua_agreement_account')
class TestDebtNettingAgreement(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.partner_a
        cls.agreement = cls.env['l10n_ua.agreement'].sudo().create({
            'code': 'AGR-N1', 'name': 'Договір №1',
            'partner_id': cls.partner.id, 'company_id': cls.env.company.id})
        cls.other_agreement = cls.env['l10n_ua.agreement'].sudo().create({
            'code': 'AGR-N2', 'name': 'Договір №2',
            'partner_id': cls.partner.id, 'company_id': cls.env.company.id})

    def _doc(self, move_type, amount, agreement):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner.id,
            'invoice_date': '2025-03-01',
            'l10n_ua_agreement_id': agreement.id,
            'invoice_line_ids': [Command.create({
                'name': 'послуга', 'quantity': 1, 'price_unit': amount,
                'tax_ids': []})],
        })
        move.action_post()
        return move

    def _netting(self, agreement=None):
        netting = self.env['l10n_ua.debt.netting'].create({
            'partner_id': self.partner.id,
            'journal_id': self.company_data['default_journal_misc'].id,
            'date': '2025-03-31',
            'l10n_ua_agreement_id': agreement.id if agreement else False,
        })
        netting.action_fill_lines()
        return netting

    def test_agreement_filters_documents(self):
        inv = self._doc('out_invoice', 1000.0, self.agreement)
        bill = self._doc('in_invoice', 400.0, self.agreement)
        self._doc('in_invoice', 700.0, self.other_agreement)
        netting = self._netting(self.agreement)
        self.assertEqual(netting.line_ids.move_id, inv | bill)
        self.assertEqual(netting.line_ids.l10n_ua_agreement_id, self.agreement)
        netting.action_post()
        self.assertEqual(netting.move_id.l10n_ua_agreement_id, self.agreement)
        self.assertEqual(netting.move_id.line_ids.l10n_ua_agreement_id, self.agreement)

    def test_foreign_agreement_line_rejected(self):
        self._doc('out_invoice', 1000.0, self.agreement)
        bill = self._doc('in_invoice', 700.0, self.other_agreement)
        netting = self._netting(self.agreement)
        with self.assertRaises(ValidationError):
            netting.line_ids = [Command.create({
                'move_line_id': bill.line_ids.filtered(
                    lambda l: l.account_id.reconcile)[:1].id})]

    def test_single_agreement_inherited_by_move(self):
        self._doc('out_invoice', 1000.0, self.agreement)
        self._doc('in_invoice', 400.0, self.agreement)
        netting = self._netting()
        netting.action_post()
        self.assertEqual(netting.move_id.l10n_ua_agreement_id, self.agreement)

    def test_mixed_agreements_left_empty(self):
        self._doc('out_invoice', 1000.0, self.agreement)
        self._doc('in_invoice', 400.0, self.other_agreement)
        netting = self._netting()
        netting.action_post()
        self.assertFalse(netting.move_id.l10n_ua_agreement_id)
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.action_report_debt_netting', netting.ids)
        self.assertIn('Договір №1', html.decode())
        self.assertIn('Договір №2', html.decode())
