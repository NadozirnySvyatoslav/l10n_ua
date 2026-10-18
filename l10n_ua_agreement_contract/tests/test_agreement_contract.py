from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgreementContract(TransactionCase):

    def test_recurring_contract_from_agreement(self):
        partner = self.env['res.partner'].create({'name': 'ТОВ Абонент', 'is_company': True})
        agreement = self.env['l10n_ua.agreement'].create({
            'name': 'Абонентське обслуговування', 'partner_id': partner.id})
        agreement.action_mark_signed()
        action = agreement.action_create_contract()
        contract = self.env['contract.contract'].browse(action['res_id'])
        self.assertEqual(contract.l10n_ua_agreement_id, agreement)
        self.assertEqual(contract.partner_id, partner)
        self.assertEqual(contract.contract_type, 'sale')
        self.assertEqual(agreement.contract_count, 1)
        self.assertEqual(agreement.action_view_contracts()['domain'],
                         [('l10n_ua_agreement_id', '=', agreement.id)])
