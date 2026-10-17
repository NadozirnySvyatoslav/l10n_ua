"""Personal API mode of the monobank provider (mocked API).

Fixtures follow the response samples of https://api.monobank.ua/docs/index.html
(v250818); only the IBANs are replaced with ones that pass the checksum.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

MODULE = 'odoo.addons.l10n_ua_bank_mono.models.l10n_ua_bank_mono_config'
OWN_IBAN = 'UA213223130000026007233566001'
OTHER_IBAN = 'UA293220010000026002700000002'
KYIV = ZoneInfo('Europe/Kyiv')


def _response(status=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = str(json_data)
    resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


def _client_info(*accounts, managed=()):
    """/personal/client-info, shaped like the documented sample."""
    return {
        'clientId': '3MSaMMtczs', 'name': 'Мазепа Іван',
        'webHookUrl': '', 'permissions': 'psfj',
        'accounts': [
            {'id': acc_id, 'sendId': 'uHWzqVoZuH', 'balance': 10000000,
             'creditLimit': 0, 'type': 'fop', 'currencyCode': currency,
             'cashbackType': 'UAH', 'maskedPan': [], 'iban': iban}
            for acc_id, iban, currency in accounts],
        'managedClients': [
            {'clientId': 'kKGVoZuHWzqVoZuH', 'tin': 1234567890,
             'name': 'Шевченко Роман Петрович',
             'accounts': [{'id': acc_id, 'balance': 0, 'creditLimit': 0,
                           'type': 'fop', 'currencyCode': 980, 'iban': iban}]}
            for acc_id, iban in managed],
    }


def _item(n, ts, amount=-95000, balance=10050000, **extra):
    """A statement item, shaped like the documented sample."""
    vals = {
        'id': f'ZuHWzqkKGVo={n}', 'time': ts, 'description': 'Покупка щастя',
        'mcc': 7997, 'originalMcc': 7997, 'hold': False, 'amount': amount,
        'operationAmount': amount, 'currencyCode': 980, 'commissionRate': 0,
        'cashbackAmount': 0, 'balance': balance, 'comment': 'За каву',
        'receiptId': 'XXXX-XXXX-XXXX-XXXX', 'invoiceId': '2103.в.27',
        'counterEdrpou': '3096889974', 'counterIban': OTHER_IBAN,
        'counterName': 'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ВОРОНА»',
    }
    vals.update(extra)
    return vals


@tagged('post_install', '-at_install')
class TestMonoPersonal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bank_account = cls.env['res.partner.bank'].create({
            'acc_number': OWN_IBAN, 'partner_id': cls.env.company.partner_id.id})
        uah = cls.env.ref('base.UAH')
        uah.active = True
        cls.journal = cls.env['account.journal'].create({
            'name': 'mono fop', 'type': 'bank', 'code': 'MNF',
            'bank_account_id': bank_account.id, 'currency_id': uah.id,
            'company_id': cls.env.company.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'mono fop', 'provider': 'mono',
            'mono_api_type': 'personal', 'mono_api_token': 'fop-token',
            'mono_account_id': 'acc-own', 'journal_id': cls.journal.id,
        })

    # --- dates and period bounds -------------------------------------------

    def test_period_bounds_are_kyiv_days(self):
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=[])) as get:
            raw = self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        low = int(datetime(2026, 9, 1, tzinfo=KYIV).timestamp())
        high = int(datetime(2026, 9, 7, 23, 59, 59, tzinfo=KYIV).timestamp())
        self.assertEqual(
            get.call_args.args[0],
            f'https://api.monobank.ua/personal/statement/acc-own/{low}/{high}')
        self.assertEqual(get.call_args.kwargs['headers'], {'X-Token': 'fop-token'})
        self.assertEqual((raw['from_ts'], raw['to_ts']), (low, high))

    def test_operation_date_is_the_kyiv_day(self):
        # 00:30 on 3 September in Kyiv is still 2 September in UTC: on a
        # server in UTC the line used to land on the previous day.
        ts = int(datetime(2026, 9, 3, 0, 30, tzinfo=KYIV).timestamp())
        trans = self.config._parse_transactions(
            {'api_type': 'statement', 'response': [_item(1, ts)]})[0]
        self.assertEqual(trans['date'], '2026-09-03')
        self.assertEqual(trans['amount'], -950.0)
        self.assertEqual(trans['receipt_id'], 'XXXX-XXXX-XXXX-XXXX')

    def test_full_month_fits_the_documented_span(self):
        """31 days + 1 hour is the documented maximum: a calendar month of
        31 days goes, 32 days do not (they used to be sent and refused)."""
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data=[])):
            self.config._fetch_from_bank(date(2026, 8, 1), date(2026, 8, 31))
        with patch(f'{MODULE}.requests.get') as get:
            with self.assertRaisesRegex(UserError, '31 days'):
                self.config._fetch_from_bank(date(2026, 8, 1), date(2026, 9, 1))
        get.assert_not_called()

    # --- pagination -----------------------------------------------------------

    def test_statement_is_read_past_a_full_page(self):
        """500 operations is a full page: the rest of the period used to be
        lost without a word."""
        end = int(datetime(2026, 9, 7, 20, tzinfo=KYIV).timestamp())
        # Newest first, counting back from `to`.
        first = [_item(n, end - n) for n in range(500)]
        second = [_item(499, end - 499)] + [
            _item(n, end - n) for n in range(500, 530)]
        with patch(f'{MODULE}.sleep') as sleep, \
                patch(f'{MODULE}.requests.get', side_effect=[
                    _response(json_data=first),
                    _response(json_data=second)]) as get:
            raw = self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertEqual(get.call_count, 2)
        # The next request ends at the oldest operation received ...
        self.assertTrue(get.call_args_list[1].args[0].endswith(f'/{end - 499}'))
        # ... after the documented one-request-per-60-seconds pause.
        sleep.assert_called_once_with(60)
        self.assertEqual(len(raw['response']), 530)
        self.assertEqual(len({i['id'] for i in raw['response']}), 530)

    def test_too_many_operations_ask_for_a_shorter_period(self):
        end = int(datetime(2026, 9, 7, 20, tzinfo=KYIV).timestamp())
        pages = [[_item(p * 500 + n, end - p * 500 - n) for n in range(500)]
                 for p in range(2)]
        with patch(f'{MODULE}.sleep'), patch(
                f'{MODULE}.requests.get',
                side_effect=[_response(json_data=p) for p in pages]):
            with self.assertRaisesRegex(UserError, 'shorten'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))

    # --- account selection ----------------------------------------------------

    def test_account_is_the_one_with_the_journal_iban(self):
        """Not "the first UAH account": that one may be a personal card."""
        self.config.mono_account_id = False
        info = _client_info(('acc-card', OTHER_IBAN, 980),
                            ('acc-fop', OWN_IBAN, 980))
        with patch(f'{MODULE}.requests.get', side_effect=[
                _response(json_data=info), _response(json_data=[])]) as get:
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertIn('/personal/statement/acc-fop/', get.call_args.args[0])
        self.assertEqual(self.config.mono_account_id, 'acc-fop')

    def test_account_shared_with_the_accountant_is_found(self):
        self.config.mono_account_id = False
        info = _client_info(('acc-card', OTHER_IBAN, 980),
                            managed=[('acc-managed', OWN_IBAN)])
        with patch(f'{MODULE}.requests.get', side_effect=[
                _response(json_data=info), _response(json_data=[])]) as get:
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertIn('/personal/statement/acc-managed/', get.call_args.args[0])

    def test_no_account_with_the_journal_iban_is_an_error(self):
        self.config.mono_account_id = False
        info = _client_info(('acc-card', OTHER_IBAN, 980))
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=info)) as get:
            with self.assertRaisesRegex(UserError, OWN_IBAN):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertEqual(get.call_count, 1)

    # --- rate limit -----------------------------------------------------------

    def test_rate_limit_is_waited_out_once(self):
        with patch(f'{MODULE}.sleep') as sleep, \
                patch(f'{MODULE}.requests.get', side_effect=[
                    _response(429, {'errorDescription': 'Too many requests'}),
                    _response(json_data=[])]) as get:
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        sleep.assert_called_once_with(60)
        self.assertEqual(get.call_count, 2)

    def test_repeated_rate_limit_names_the_wait(self):
        with patch(f'{MODULE}.sleep') as sleep, \
                patch(f'{MODULE}.requests.get', return_value=_response(
                    429, {'errorDescription': 'Too many requests'})):
            with self.assertRaisesRegex(UserError, '60 seconds'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        sleep.assert_called_once_with(60)

    def test_api_error_description_is_shown(self):
        with patch(f'{MODULE}.requests.get', return_value=_response(
                400, {'errorDescription': "Unknown 'X-Token'"})):
            with self.assertRaisesRegex(UserError, "Unknown 'X-Token'"):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))

    # --- balances -------------------------------------------------------------

    def test_balances_come_from_the_operations(self):
        """Each operation carries the balance after it: the statement is
        verified instead of always being derived."""
        ts = int(datetime(2026, 9, 2, 12, tzinfo=KYIV).timestamp())
        raw = {'api_type': 'statement', 'response': [
            # Newest first.
            _item(2, ts + 60, amount=-95000, balance=10050000),
            _item(1, ts, amount=20000, balance=10145000),
        ]}
        self.assertEqual(self.config._extract_balances(raw), (101250.0, 100500.0))

        job = self.env['l10n_ua.bank.sync.job'].create({
            'config_id': self.config.id,
            'date_from': '2026-09-01', 'date_to': '2026-09-07'})
        opening, closing = self.config._extract_balances(raw)
        statement = job._create_native_statement(
            self.config._parse_transactions(raw), opening, closing)
        self.assertTrue(statement.l10n_ua_balance_verified)
        self.assertTrue(statement.l10n_ua_balance_ok)
        self.assertEqual(
            set(statement.line_ids.mapped('l10n_ua_mono_receipt_id')),
            {'XXXX-XXXX-XXXX-XXXX'})

    def test_no_operations_no_balances(self):
        self.assertEqual(self.config._extract_balances(
            {'api_type': 'statement', 'response': []}), (None, None))

    # --- token ----------------------------------------------------------------

    def test_token_is_hidden_from_accountants_but_sync_works(self):
        accountant = new_test_user(
            self.env, login='mono_accountant',
            groups='base.group_user,l10n_ua_account_base.group_ua_accountant')
        config = self.config.with_user(accountant)
        with self.assertRaises(AccessError):
            config.read(['mono_api_token'])
        self.assertTrue(config.mono_has_token)
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=[])) as get:
            config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertEqual(get.call_args.kwargs['headers'], {'X-Token': 'fop-token'})

    def test_token_is_not_logged(self):
        with self.assertLogs(MODULE, level='DEBUG') as logs, \
                patch(f'{MODULE}.requests.get',
                      return_value=_response(json_data=[])):
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertNotIn('fop-token', '\n'.join(logs.output))

    def test_webhook_fields_are_gone(self):
        """They were shown on the form, but nothing served or registered
        the webhook."""
        fields = self.env['l10n_ua.bank.sync.config']._fields
        self.assertNotIn('mono_webhook_url', fields)
        self.assertNotIn('mono_webhook_active', fields)
