"""Corporate API mode of the monobank provider (mocked API)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MODULE = 'odoo.addons.l10n_ua_bank_mono.models.l10n_ua_bank_mono_config'
OWN_IBAN = 'UA213223130000026007233566001'
KYIV = ZoneInfo('Europe/Kyiv')


def _response(status=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = str(json_data)
    resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


def _item(n, ts, **extra):
    vals = {'id': f'op-{n}', 'time': ts, 'amount': 10000,
            'description': f'Операція {n}', 'status': 'DONE'}
    vals.update(extra)
    return vals


@tagged('post_install', '-at_install')
class TestMonoCorporate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bank_account = cls.env['res.partner.bank'].create({
            'acc_number': OWN_IBAN, 'partner_id': cls.env.company.partner_id.id})
        uah = cls.env.ref('base.UAH')
        uah.active = True
        cls.journal = cls.env['account.journal'].create({
            'name': 'mono corp', 'type': 'bank', 'code': 'MNC',
            'bank_account_id': bank_account.id, 'currency_id': uah.id,
            'company_id': cls.env.company.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'mono corp', 'provider': 'mono',
            'mono_api_type': 'corporate', 'mono_api_token': 'corp-token',
            'journal_id': cls.journal.id,
        })

    def test_personal_is_the_default(self):
        config = self.env['l10n_ua.bank.sync.config'].create({
            'name': 'mono personal', 'provider': 'mono',
            'journal_id': self.journal.id})
        self.assertEqual(config.mono_api_type, 'personal')

    def test_statement_goes_to_corporate_api_with_journal_iban(self):
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=[])) as get:
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        url = get.call_args.args[0]
        self.assertTrue(url.startswith(
            f'https://corp-api.monobank.ua/ext/v1/statement/{OWN_IBAN}/'))
        self.assertEqual(get.call_args.kwargs['headers']['x-token'], 'corp-token')
        # Without an explicit limit the API returns only 10 operations.
        self.assertEqual(get.call_args.kwargs['params'], {'limit': 500})

    def test_period_bounds_are_kyiv_days(self):
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data=[])):
            raw = self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertEqual(
            raw['from_ts'],
            int(datetime(2026, 9, 1, tzinfo=KYIV).timestamp()))
        self.assertEqual(
            raw['to_ts'],
            int(datetime(2026, 9, 7, 23, 59, 59, tzinfo=KYIV).timestamp()))

    def test_statement_is_read_past_one_page(self):
        start = int(datetime(2026, 9, 1, tzinfo=KYIV).timestamp())
        first = [_item(n, start + n) for n in range(500)]
        # The next page starts at the second of the last one received, so
        # that one comes again and must not be counted twice.
        second = [_item(499, start + 499)] + [
            _item(n, start + n) for n in range(500, 520)]
        with patch(f'{MODULE}.requests.get', side_effect=[
                _response(json_data=first), _response(json_data=second)]) as get:
            raw = self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        self.assertEqual(get.call_count, 2)
        self.assertIn(f'/{start + 499}/', get.call_args_list[1].args[0])
        self.assertEqual(len(raw['response']), 520)

    def test_only_done_operations_are_imported(self):
        ts = int(datetime(2026, 9, 2, 12, tzinfo=KYIV).timestamp())
        raw = {'api_type': 'corp_statement', 'response': [
            _item(1, ts),
            _item(2, ts, status='PENDING'),
            _item(3, ts, status='DECLINED'),
        ]}
        transactions = self.config._parse_transactions(raw)
        self.assertEqual([t['id'] for t in transactions], ['op-1'])
        self.assertEqual(transactions[0]['amount'], 100.0)

    def test_booking_date_is_the_kyiv_day_of_completion(self):
        # 00:30 in Kyiv is still the previous day in UTC.
        created = int(datetime(2026, 9, 2, 20, tzinfo=KYIV).timestamp())
        completed = int(datetime(2026, 9, 3, 0, 30, tzinfo=KYIV).timestamp())
        raw = {'api_type': 'corp_statement', 'response': [
            _item(1, created, completedTime=completed, amount=-5050,
                  counterName='ТОВ Приклад', counterEdrpou='21133352',
                  counterIban='UA293220010000026000000000001')]}
        trans = self.config._parse_transactions(raw)[0]
        self.assertEqual(trans['date'], '2026-09-03')
        self.assertEqual(trans['amount'], -50.5)
        self.assertEqual(trans['partner_edrpou'], '21133352')

    def test_short_rate_limit_is_waited_out(self):
        """A statement takes several calls; a short wait must not fail it."""
        limited = _response(429, {'errorCode': 'TOO_MANY'},
                            headers={'x-rate-limit-retry-after-seconds': '17'})
        with patch(f'{MODULE}.sleep') as sleep, \
                patch(f'{MODULE}.requests.get',
                      side_effect=[limited, _response(json_data=[])]) as get:
            self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        sleep.assert_called_once_with(17)
        self.assertEqual(get.call_count, 2)

    def test_long_rate_limit_names_the_wait(self):
        with patch(f'{MODULE}.sleep') as sleep, \
                patch(f'{MODULE}.requests.get', return_value=_response(
                    429, {'errorCode': 'TOO_MANY'},
                    headers={'x-rate-limit-retry-after-seconds': '600'})):
            with self.assertRaisesRegex(UserError, '600'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        sleep.assert_not_called()

    def test_personal_account_id_is_not_sent_as_iban(self):
        """Left over from the personal API before the switch."""
        self.config.mono_account_id = 'kKGVoZuHWzqVoZuH'
        with patch(f'{MODULE}.requests.get') as get:
            with self.assertRaisesRegex(UserError, 'not an IBAN'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
        get.assert_not_called()

    def test_api_error_description_is_shown(self):
        with patch(f'{MODULE}.requests.get', return_value=_response(
                403, {'errorCode': 'FORBIDDEN', 'errorDescription': 'Токен недійсний'})):
            with self.assertRaisesRegex(UserError, 'Токен недійсний'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))

    def test_connection_warns_when_journal_account_is_missing(self):
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data=[
                {'iban': 'UA293220010000026002700000002', 'currency': 980,
                 'balance': 42.0}])):
            action = self.config.action_test_connection()
        self.assertEqual(action['params']['type'], 'warning')

        with patch(f'{MODULE}.requests.get', return_value=_response(json_data=[
                {'iban': OWN_IBAN, 'currency': 980, 'balance': 42.0}])) as get:
            action = self.config.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        self.assertEqual(
            get.call_args.args[0], 'https://corp-api.monobank.ua/ext/v1/accounts')

    def test_personal_mode_keeps_personal_api(self):
        self.config.mono_api_type = 'personal'
        with patch(f'{MODULE}.requests.get', return_value=_response(
                json_data={'name': 'ФОП', 'accounts': []})) as get:
            self.config.action_test_connection()
        self.assertEqual(
            get.call_args.args[0], 'https://api.monobank.ua/personal/client-info')

    def test_pending_at_period_end_is_picked_up_by_the_next_period(self):
        """Created on the last day of one sync, booked on the first day of
        the next: the manual sync starts the next period the day after, so
        the query has to reach back to find it."""
        created = int(datetime(2026, 9, 7, 23, tzinfo=KYIV).timestamp())
        booked = int(datetime(2026, 9, 8, 9, tzinfo=KYIV).timestamp())
        item = _item(1, created, completedTime=booked)
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=[item])) as get:
            raw = self.config._fetch_from_bank(date(2026, 9, 8), date(2026, 9, 14))
        query_from = int(get.call_args.args[0].split('/')[-2])
        self.assertLessEqual(query_from, created)
        self.assertEqual(
            [t['id'] for t in self.config._parse_transactions(raw)], ['op-1'])

    def test_operation_booked_before_the_period_is_left_to_its_own(self):
        """The look-back fetches operations of the previous period too; they
        belong to that statement and must not be imported twice over here."""
        booked = int(datetime(2026, 9, 7, 12, tzinfo=KYIV).timestamp())
        with patch(f'{MODULE}.requests.get', return_value=_response(
                json_data=[_item(1, booked)])):
            raw = self.config._fetch_from_bank(date(2026, 9, 8), date(2026, 9, 14))
        self.assertEqual(self.config._parse_transactions(raw), [])

    def test_long_period_is_split_into_31_day_requests(self):
        with patch(f'{MODULE}.requests.get',
                   return_value=_response(json_data=[])) as get:
            self.config._fetch_from_bank(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(get.call_count, 2)
        for call in get.call_args_list:
            low, high = map(int, call.args[0].split('/')[-2:])
            self.assertLessEqual(high - low, 31 * 86400)

    def test_a_full_page_within_one_second_is_not_lost_quietly(self):
        ts = int(datetime(2026, 9, 2, 12, tzinfo=KYIV).timestamp())
        page = [_item(n, ts) for n in range(500)]
        with patch(f'{MODULE}.requests.get', side_effect=[
                _response(json_data=page), _response(json_data=page)]):
            with self.assertRaisesRegex(UserError, 'one second'):
                self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 7))
