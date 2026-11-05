"""Payment orders prepared through the monobank Corporate API (mocked)."""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MODULE = 'odoo.addons.l10n_ua_bank_mono.models.l10n_ua_bank_mono_config'
OWN_IBAN = 'UA213223130000026007233566001'
RECIPIENT_IBAN = 'UA113052990000026007891234567'


def _response(status=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = str(json_data)
    resp.content = b'{}' if json_data is not None else b''
    resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


@tagged('post_install', '-at_install')
class TestMonoPayment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.company_registry = '12345678'
        uah = cls.env.ref('base.UAH')
        uah.active = True
        cls.bank_account = cls.env['res.partner.bank'].create({
            'acc_number': OWN_IBAN, 'partner_id': cls.env.company.partner_id.id})
        cls.journal = cls.env['account.journal'].create({
            'name': 'mono corp', 'type': 'bank', 'code': 'MNP',
            'bank_account_id': cls.bank_account.id, 'currency_id': uah.id,
            'company_id': cls.env.company.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'mono corp', 'provider': 'mono',
            'mono_api_type': 'corporate', 'mono_api_token': 'corp-token',
            'journal_id': cls.journal.id,
        })

    def _order(self, lines=None):
        order = self.env['l10n_ua.bank.payment'].create({
            'payer_account_id': self.bank_account.id,
            'transfer_method': 'mono_api',
            'line_ids': [(0, 0, vals) for vals in (lines or [{
                'recipient_name': 'ТОВ Постачальник',
                'recipient_edrpou': '87654321',
                'recipient_iban': RECIPIENT_IBAN,
                'amount': 1500.50,
                'purpose': 'Оплата за товар згідно рахунку №1',
            }])],
        })
        return order

    def test_connection_found_by_payer_iban(self):
        self.assertEqual(self._order().mono_config_id, self.config)

    def test_prepare_sends_payment_with_idempotency_key(self):
        order = self._order()
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-1'})) as post:
            order.action_mono_send()
        call = post.call_args
        self.assertEqual(call.args[0],
                         'https://corp-api.monobank.ua/ext/v1/payment/prepare')
        headers = call.kwargs['headers']
        self.assertEqual(headers['x-token'], 'corp-token')
        self.assertTrue(headers['idempotency-key'])
        body = call.kwargs['json']
        self.assertEqual(body['senderIban'], OWN_IBAN)
        self.assertEqual(body['receiver'], {
            'iban': RECIPIENT_IBAN, 'edrpou': '87654321', 'name': 'ТОВ Постачальник'})
        self.assertEqual(body['amount'], 150050)
        self.assertEqual(body['currency'], '980')
        self.assertNotIn('payCode', body)
        line = order.line_ids
        self.assertEqual(body['externalReference'], line.mono_external_ref)
        self.assertEqual(line.mono_payment_id, 'pay-1')
        self.assertEqual(line.mono_state, 'draft')
        self.assertEqual(order.state, 'sent')
        self.assertEqual(order.mono_status, 'pending')

    def test_same_payment_same_idempotency_key(self):
        order = self._order()
        line = order.line_ids
        payload = line._mono_payload(OWN_IBAN)
        self.assertEqual(line._mono_keys(payload), line._mono_keys(payload))
        changed = dict(payload, amount=1)
        self.assertNotEqual(line._mono_keys(payload)[1], line._mono_keys(changed)[1])

    def test_budget_payment(self):
        order = self._order([{
            'recipient_name': 'ГУК у м.Києві',
            'recipient_edrpou': '37993783',
            'recipient_iban': RECIPIENT_IBAN,
            'amount': 100.0,
            'mono_pay_code': '101',
            'mono_additional_info': 'єдиний податок за жовтень',
            'mono_ultimate_debit_name': 'ТОВ ПРИКЛАД',
            'mono_ultimate_debit_code': '11111111',
        }])
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-b'})) as post:
            order.action_mono_send()
        body = post.call_args.kwargs['json']
        self.assertEqual(body['payCode'], '101')
        self.assertEqual(body['additionalInfo'], 'єдиний податок за жовтень')
        self.assertEqual(body['destination'],
                         '101 єдиний податок за жовтень ЄДРПОУ 12345678')
        self.assertEqual(body['ultimateDebit'], {'id': '11111111', 'name': 'ТОВ ПРИКЛАД'})

    def test_invalid_line_sends_nothing(self):
        order = self._order([{
            'recipient_name': 'Без коду', 'recipient_iban': RECIPIENT_IBAN,
            'amount': 10.0, 'purpose': 'Оплата послуг',
        }])
        with patch(f'{MODULE}.requests.post') as post:
            with self.assertRaisesRegex(UserError, 'EDRPOU'):
                order.action_mono_send()
        post.assert_not_called()

    def test_bank_error_kept_on_line(self):
        good = {'recipient_name': 'Перший', 'recipient_edrpou': '11111111',
                'recipient_iban': RECIPIENT_IBAN, 'amount': 10.0,
                'purpose': 'Оплата послуг 1'}
        order = self._order([good, dict(good, recipient_name='Другий',
                                        purpose='Оплата послуг 2')])
        with patch(f'{MODULE}.requests.post', side_effect=[
                _response(json_data={'id': 'pay-1'}),
                _response(400, {'errorCode': 'INVALID_RECEIVER',
                                'errorDescription': 'Невірний отримувач'})]):
            order.action_mono_send()
        first, second = order.line_ids.sorted('id')
        self.assertEqual(first.mono_payment_id, 'pay-1')
        self.assertEqual(second.mono_state, 'error')
        self.assertIn('Невірний отримувач', second.mono_error)
        self.assertIn('INVALID_RECEIVER', second.mono_error)
        self.assertNotEqual(order.state, 'sent')
        self.assertEqual(order.mono_status, 'error')
        self.assertTrue(order.mono_unsent)
        # Sent again: only the rejected one goes.
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-2'})) as post:
            order.action_mono_send()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(second.mono_payment_id, 'pay-2')
        self.assertEqual(order.state, 'sent')
        # A prepared payment is frozen.
        with self.assertRaises(UserError):
            first.amount = 20.0

    def test_state_refresh_and_statement_link(self):
        order = self._order()
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-1'})):
            order.action_mono_send()
        line = order.line_ids
        with patch(f'{MODULE}.requests.get', return_value=_response(
                json_data={'id': 'pay-1', 'state': 'DECLINED'})) as get:
            order.action_mono_refresh()
        self.assertIn('/ext/v1/payment/pay-1/state', get.call_args.args[0])
        self.assertEqual(line.mono_state, 'declined')
        self.assertEqual(order.mono_status, 'declined')

        with patch(f'{MODULE}.requests.get', return_value=_response(
                json_data={'id': 'pay-1', 'state': 'IN_STATEMENT'})):
            order.action_mono_refresh()
        self.assertEqual(line.mono_state, 'in_statement')
        self.assertFalse(line.mono_statement_line_id)
        # The statement line of the executed payment carries its reference.
        st_line = self.env['account.bank.statement.line'].create({
            'journal_id': self.journal.id,
            'date': '2026-10-01',
            'payment_ref': 'Оплата за товар',
            'amount': -1500.50,
            'l10n_ua_mono_external_ref': line.mono_external_ref,
        })
        self.assertEqual(line.mono_statement_line_id, st_line)
        self.assertEqual(order.mono_status, 'done')

    def test_cron_refresh(self):
        order = self._order()
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-1'})):
            order.action_mono_send()
        with patch(f'{MODULE}.requests.get', return_value=_response(
                json_data={'id': 'pay-1', 'state': 'IN_STATEMENT'})):
            self.env['l10n_ua.bank.payment']._cron_mono_refresh()
        self.assertEqual(order.line_ids.mono_state, 'in_statement')

    def test_no_connection_for_other_account(self):
        other = self.env['res.partner.bank'].create({
            'acc_number': 'UA903052992990004149123456789',
            'partner_id': self.env.company.partner_id.id})
        order = self.env['l10n_ua.bank.payment'].create({
            'payer_account_id': other.id, 'transfer_method': 'mono_api',
            'line_ids': [(0, 0, {'recipient_name': 'X', 'recipient_edrpou': '1',
                                 'recipient_iban': RECIPIENT_IBAN, 'amount': 1,
                                 'purpose': 'purpose'})]})
        self.assertFalse(order.mono_config_id)
        with self.assertRaisesRegex(UserError, 'No monobank corporate API connection'):
            order.action_mono_send()

    def test_file_method_untouched(self):
        order = self._order()
        order.transfer_method = 'file'
        order.action_generate_file()
        self.assertEqual(order.state, 'generated')

    def test_accountant_sends_without_seeing_token(self):
        user = self.env['res.users'].create({
            'name': 'Бухгалтер', 'login': 'mono_pay_accountant',
            'group_ids': [(6, 0, [self.env.ref('account.group_account_user').id])],
        })
        order = self._order().with_user(user)
        self.assertEqual(order.mono_config_id, self.config)
        with patch(f'{MODULE}.requests.post',
                   return_value=_response(json_data={'id': 'pay-u'})) as post:
            order.action_mono_send()
        self.assertEqual(post.call_args.kwargs['headers']['x-token'], 'corp-token')
        self.assertEqual(order.line_ids.mono_payment_id, 'pay-u')
