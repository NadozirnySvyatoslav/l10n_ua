"""API «Автоклієнт» ПриватБанку: пачки, заголовки, розбір, залишки, помилки.

Фікстури — приклади відповідей з офіційного «Опису API Автоклієнт»
(посилання з https://privatbank.ua/business/intehratsiya). HTTP повністю
підмінений, у мережу тести не ходять.
"""

import copy
import json
import logging
from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

MOD = 'odoo.addons.l10n_ua_bank_privat.models.l10n_ua_bank_privat_config'
TOKEN = '8b34f865-a75b-40b6-8SECRET3NAx6+H8w0fouhmHyvgDa8K/3AqaVzOLiDZew=='
IBAN = 'UA943052990000026100050001037'

SETTINGS = {
    'status': 'SUCCESS', 'type': 'settings',
    'settings': {
        'phase': 'WRK', 'today': '30.03.2020 00:00:00',
        'lastday': '29.03.2020 00:00:00', 'work_balance': 'N',
        'server_date_time': '30.03.2020 12:03:51',
        'date_final_statement': '28.03.2020 00:00:00',
    },
}

# Транзакція з прикладу документації (кредит, проведена).
TX_CREDIT = {
    'AUT_MY_CRF': '31451288', 'AUT_MY_MFO': '305299',
    'AUT_MY_ACC': '26184050001514',
    'AUT_MY_NAM': 'Програмiсти та Ko МСБ-ТЕСТ ТОВ',
    'AUT_CNTR_CRF': '14360570', 'AUT_CNTR_MFO': '305299',
    'AUT_CNTR_ACC': '70214924104032',
    'AUT_CNTR_NAM': 'ПРОЦ ВИТР ЗА СТРОК КОШТ СУБ(UAH)',
    'CCY': 'UAH', 'FL_REAL': 'r', 'PR_PR': 'r', 'DOC_TYP': 'm',
    'NUM_DOC': 'K0108B1WKX', 'DAT_KL': '07.01.2020', 'DAT_OD': '07.01.2020',
    'OSND': 'Нарахування вiдсоткiв згiдно з депозитним договором N...',
    'SUM': '0.01', 'SUM_E': '0.01', 'REF': 'DNCHK0108B1WKX', 'REFN': '1',
    'TIM_P': '02:58', 'DATE_TIME_DAT_OD_TIM_P': '07.01.2020 02:58:00',
    'ID': '557091731', 'TRANTYPE': 'C', 'DLR': 'J63DNDSM0XHY5',
    'TECHNICAL_TRANSACTION_ID': '557091731_online',
}


def _tx(**kw):
    tx = copy.deepcopy(TX_CREDIT)
    tx.update(kw)
    return tx


# Списання — контрагент, ЄДРПОУ, сума у валюті рахунку.
TX_DEBIT = _tx(
    TRANTYPE='D', SUM='1500.50', SUM_E='1500.50', REF='DNCHPAY0001', REFN='1',
    ID='557091800', DAT_OD='08.01.2020',
    DATE_TIME_DAT_OD_TIM_P='08.01.2020 10:15:00',
    AUT_CNTR_CRF='12345678', AUT_CNTR_ACC='UA213223130000026007233566001',
    AUT_CNTR_NAM='ТОВ «Постачальник»', OSND='Оплата за товар згідно рах. 17')
# Друга частина того самого проведення (інший REFN) — окремий рядок.
TX_DEBIT_FEE = _tx(
    TRANTYPE='D', SUM='5.00', SUM_E='5.00', REF='DNCHPAY0001', REFN='2',
    ID='557091801', DAT_OD='08.01.2020', OSND='Комісія за платіж')
TX_PENDING = _tx(PR_PR='p', REF='DNCHPEND01', ID='557091900', SUM='10.00')
TX_STORNO = _tx(PR_PR='t', REF='DNCHSTOR01', ID='557091901', SUM='20.00')


def _balance(**kw):
    bal = {
        'acc': IBAN, 'currency': 'UAH',
        'balanceIn': '1000.00', 'balanceInEq': '1000.00',
        'balanceOut': '0.00', 'balanceOutEq': '0.00',
        'turnoverDebt': '0.00', 'turnoverDebtEq': '0.00',
        'turnoverCred': '0.00', 'turnoverCredEq': '0.00',
        'bgfIBrnm': ' ', 'brnm': 'DNH0', 'dpd': '09.03.2020 00:00:00',
        'nameACC': 'Програмiсти та Ko МСБ-ТЕСТ ТОВ', 'state': 'l',
        'atp': 'D', 'flmn': 'DN', 'is_final_bal': True,
    }
    bal.update(kw)
    return bal


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


class FakeBank:
    """Імітація acp.privatbank.ua: маршрутизація за шляхом і followId."""

    def __init__(self, tx_pages=None, bal_pages=None, settings=None,
                 override=None):
        self.tx_pages = tx_pages or [[]]
        self.bal_pages = bal_pages or [[]]
        self.settings = settings or SETTINGS
        self.override = override or {}
        self.calls = []

    @staticmethod
    def _page(pages, key, params, typ):
        follow = params.get('followId')
        idx = int(follow.split('_')[1]) if follow else 0
        more = idx + 1 < len(pages)
        return {
            'status': 'SUCCESS', 'type': typ,
            'exist_next_page': more,
            'next_page_id': 'page_%d' % (idx + 1) if more else '',
            key: pages[idx],
        }

    def __call__(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append({'url': url, 'headers': dict(headers or {}),
                           'params': params})
        path = url.split('/api', 1)[1]
        if path in self.override:
            return self.override[path]
        if path == '/statements/settings':
            return FakeResponse(200, self.settings)
        if path == '/statements/transactions':
            return FakeResponse(200, self._page(
                self.tx_pages, 'transactions', params, 'transactions'))
        if path == '/statements/balance':
            return FakeResponse(200, self._page(
                self.bal_pages, 'balances', params, 'balances'))
        return FakeResponse(404, {'status': 'ERROR', 'message': 'not found'})


@tagged('post_install', '-at_install')
class TestPrivatAutoclient(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env.company.partner_id
        cls.bank_acc = cls.env['res.partner.bank'].create({
            'acc_number': IBAN, 'partner_id': partner.id})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Privat API', 'type': 'bank', 'code': 'PAPI',
            'company_id': cls.env.company.id,
            'bank_account_id': cls.bank_acc.id})
        cls.cfg = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'Privat API', 'provider': 'privat',
            'journal_id': cls.journal.id,
            'privat_api_token': TOKEN})

    def _run(self, bank, cfg=None, d_from=date(2020, 1, 1), d_to=date(2020, 1, 31)):
        cfg = cfg or self.cfg
        with patch(MOD + '.requests.get', side_effect=bank), \
                patch(MOD + '.sleep'):
            return cfg._fetch_from_bank(d_from, d_to)

    # ---- пачки / заголовки / параметри ----

    def test_all_pages_fetched_via_follow_id(self):
        page1 = [_tx(REF='R%03d' % i, ID=str(i)) for i in range(100)]
        page2 = [_tx(REF='R%03d' % i, ID=str(i)) for i in range(100, 150)]
        bank = FakeBank(tx_pages=[page1, page2])
        raw = self._run(bank)
        txs = self.cfg._parse_transactions(raw)
        self.assertEqual(len(txs), 150)
        tx_calls = [c for c in bank.calls
                    if c['url'].endswith('/statements/transactions')]
        self.assertEqual(len(tx_calls), 2)
        self.assertNotIn('followId', tx_calls[0]['params'])
        self.assertEqual(tx_calls[1]['params']['followId'], 'page_1')
        for call in tx_calls:
            self.assertEqual(call['params']['limit'], 100)

    def test_repeated_page_id_stops_with_error(self):
        resp = FakeResponse(200, {
            'status': 'SUCCESS', 'type': 'transactions',
            'exist_next_page': True, 'next_page_id': 'same',
            'transactions': [TX_CREDIT]})
        bank = FakeBank(override={'/statements/transactions': resp})
        with self.assertRaises(UserError):
            self._run(bank)

    def test_headers_and_params(self):
        bank = FakeBank(tx_pages=[[TX_CREDIT]])
        self._run(bank)
        self.assertEqual(
            [c['url'] for c in bank.calls],
            ['https://acp.privatbank.ua/api/statements/settings',
             'https://acp.privatbank.ua/api/statements/transactions',
             'https://acp.privatbank.ua/api/statements/balance'])
        for call in bank.calls:
            self.assertEqual(call['headers']['token'], TOKEN)
            self.assertTrue(call['headers']['User-Agent'])
            self.assertEqual(call['headers']['Content-Type'],
                             'application/json;charset=utf-8')
            self.assertNotIn('id', call['params'])
        params = bank.calls[1]['params']
        # IBAN узято з рахунку журналу, дати — ДД-ММ-РРРР.
        self.assertEqual(params['acc'], IBAN)
        self.assertEqual(params['startDate'], '01-01-2020')
        self.assertEqual(params['endDate'], '31-01-2020')

    def test_group_client_id_param(self):
        self.cfg.privat_group_client_id = '4400000005'
        bank = FakeBank()
        self._run(bank)
        self.assertTrue(all(c['params'].get('id') == '4400000005'
                            for c in bank.calls))

    def test_iban_required(self):
        cfg = self.cfg.copy({'privat_api_token': TOKEN})
        cfg.journal_id = self.env['account.journal'].create({
            'name': 'No acc', 'type': 'bank', 'code': 'PNOA'})
        bank = FakeBank()
        with self.assertRaises(UserError):
            self._run(bank, cfg=cfg)
        self.assertFalse(bank.calls, 'no request without an account')
        cfg.privat_account_iban = '26001234567890'
        with self.assertRaises(UserError):
            self._run(bank, cfg=cfg)
        self.assertFalse(bank.calls)

    # ---- розбір ----

    def test_parse_credit_debit_counterparty(self):
        raw = self._run(FakeBank(tx_pages=[
            [TX_CREDIT, TX_DEBIT, TX_DEBIT_FEE, TX_PENDING, TX_STORNO]]))
        txs = {t['id']: t for t in self.cfg._parse_transactions(raw)}
        # Лише проведені (PR_PR = r); ключ — REF+REFN.
        self.assertEqual(set(txs), {
            'DNCHK0108B1WKX/1', 'DNCHPAY0001/1', 'DNCHPAY0001/2'})
        credit = txs['DNCHK0108B1WKX/1']
        self.assertEqual(credit['amount'], 0.01)
        self.assertEqual(credit['date'], '2020-01-07')
        self.assertEqual(credit['partner_edrpou'], '14360570')
        self.assertEqual(credit['partner_iban'], '70214924104032')
        self.assertEqual(credit['partner_name'],
                         'ПРОЦ ВИТР ЗА СТРОК КОШТ СУБ(UAH)')
        self.assertTrue(credit['description'].startswith('Нарахування'))
        debit = txs['DNCHPAY0001/1']
        # «Оплата» у призначенні не впливає на знак — лише TRANTYPE.
        self.assertEqual(debit['amount'], -1500.50)
        self.assertEqual(debit['date'], '2020-01-08')
        self.assertEqual(debit['partner_edrpou'], '12345678')
        self.assertEqual(debit['partner_iban'], 'UA213223130000026007233566001')
        self.assertEqual(txs['DNCHPAY0001/2']['amount'], -5.0)

    def test_incoming_payment_word_keeps_sign(self):
        tx = _tx(OSND='Оплата за послуги згідно рахунку 5', SUM='750.00')
        txs = self.cfg._privat_parse_autoclient({'transactions': [tx]})
        self.assertEqual(txs[0]['amount'], 750.0)

    def test_missing_trantype_is_an_error(self):
        tx = _tx()
        del tx['TRANTYPE']
        with self.assertRaises(UserError):
            self.cfg._privat_parse_autoclient({'transactions': [tx]})

    # ---- залишки ----

    def test_balances_single_record(self):
        bal = _balance(balanceIn='1000.00', turnoverCred='0.01',
                       turnoverDebt='1505.50', balanceOut='-505.49')
        raw = self._run(FakeBank(
            tx_pages=[[TX_CREDIT, TX_DEBIT, TX_DEBIT_FEE]],
            bal_pages=[[bal, _balance(acc='UA000000000000000000000000001')]]))
        self.assertEqual(self.cfg._extract_balances(raw), (1000.0, -505.49))

    def test_balances_per_day_any_order(self):
        day1 = _balance(balanceIn='100.00', turnoverCred='50.00',
                        balanceOut='150.00')
        day2 = _balance(balanceIn='150.00', turnoverDebt='30.00',
                        balanceOut='120.00')
        for rows in ([day1, day2], [day2, day1]):
            raw = {'api_type': 'autoclient', 'acc': IBAN, 'balances': rows}
            self.assertEqual(self.cfg._extract_balances(raw), (100.0, 120.0))

    def test_balances_not_chaining_unverified(self):
        raw = {'api_type': 'autoclient', 'acc': IBAN, 'balances': [
            _balance(balanceIn='100.00', turnoverCred='1.00',
                     balanceOut='500.00')]}
        self.assertEqual(self.cfg._extract_balances(raw), (None, None))

    def test_balance_failure_keeps_transactions(self):
        bank = FakeBank(tx_pages=[[TX_CREDIT]], override={
            '/statements/balance': FakeResponse(500, None, text='oops')})
        raw = self._run(bank)
        self.assertEqual(len(self.cfg._parse_transactions(raw)), 1)
        self.assertEqual(self.cfg._extract_balances(raw), (None, None))

    def test_job_end_to_end_verified_statement(self):
        bal = _balance(balanceIn='1000.00', turnoverCred='0.01',
                       turnoverDebt='1505.50', balanceOut='-505.49')
        bank = FakeBank(tx_pages=[[TX_CREDIT, TX_DEBIT], [TX_DEBIT_FEE, TX_PENDING]],
                        bal_pages=[[bal]])
        with patch(MOD + '.requests.get', side_effect=bank), \
                patch(MOD + '.sleep'):
            self.cfg._create_and_run_job(date(2020, 1, 1), date(2020, 1, 31))
        job = self.cfg.last_sync_job_id
        self.assertEqual(job.state, 'done')
        stmt = job.bank_statement_id
        self.assertEqual(len(stmt.line_ids), 3)
        self.assertEqual(stmt.balance_start, 1000.0)
        self.assertEqual(stmt.balance_end_real, -505.49)
        self.assertTrue(stmt.l10n_ua_balance_verified)
        self.assertNotIn(TOKEN, job.raw_payload)
        # Повторна синхронізація того ж періоду не дублює рядки.
        bank2 = FakeBank(tx_pages=[[TX_CREDIT, TX_DEBIT, TX_DEBIT_FEE]],
                         bal_pages=[[bal]])
        with patch(MOD + '.requests.get', side_effect=bank2), \
                patch(MOD + '.sleep'):
            self.cfg._create_and_run_job(date(2020, 1, 1), date(2020, 1, 31))
        self.assertFalse(self.cfg.last_sync_job_id.bank_statement_id)

    # ---- помилки ----

    def test_http_401_error(self):
        bank = FakeBank(override={'/statements/settings': FakeResponse(401, {
            'status': 'ERROR', 'code': '401', 'message': 'Unauthorized'})})
        with self.assertRaisesRegex(UserError, '401'):
            self._run(bank)

    def test_error_status_in_body(self):
        bank = FakeBank(override={'/statements/transactions': FakeResponse(200, {
            'status': 'ERROR', 'code': 'VE005',
            'message': 'Помилкові параметри: asac',
            'requestId': 'ae16785e'})})
        with self.assertRaisesRegex(UserError, 'Помилкові параметри'):
            self._run(bank)

    def test_http_400_error_body(self):
        bank = FakeBank(override={'/statements/transactions': FakeResponse(400, {
            'status': 'ERROR', 'code': '400', 'message': 'invalid acc',
            'requestId': '20240223_131617_286f', 'serviceCode': 'X'})})
        with self.assertRaisesRegex(UserError, 'invalid acc'):
            self._run(bank)

    def test_maintenance_blocks_requests(self):
        settings = copy.deepcopy(SETTINGS)
        settings['settings']['work_balance'] = 'Y'
        bank = FakeBank(settings=settings)
        with self.assertRaises(UserError):
            self._run(bank)
        self.assertEqual(len(bank.calls), 1)

    # ---- безпека токена ----

    def test_token_never_logged(self):
        bank = FakeBank(tx_pages=[[TX_CREDIT], [TX_DEBIT]], override={
            '/statements/balance': FakeResponse(401, {'status': 'ERROR'})})
        logger = logging.getLogger('odoo.addons.l10n_ua_bank_privat')
        with self.assertLogs(logger, level='DEBUG') as logs:
            self._run(bank)
        self.assertTrue(logs.output)
        for line in logs.output:
            self.assertNotIn(TOKEN, line)
            self.assertNotIn('8SECRET3', line)

    def test_token_restricted_to_manager(self):
        self.assertEqual(self.cfg._fields['privat_api_token'].groups,
                         'l10n_ua_account_base.group_ua_manager')
        accountant = new_test_user(
            self.env, login='privat_acc',
            groups='base.group_user,l10n_ua_account_base.group_ua_accountant')
        cfg = self.cfg.with_user(accountant)
        with self.assertRaises(AccessError):
            cfg.read(['privat_api_token'])
        # Але синхронізацію бухгалтер запускає: токен читається через sudo.
        bank = FakeBank(tx_pages=[[TX_CREDIT]])
        raw = self._run(bank, cfg=cfg)
        self.assertEqual(bank.calls[0]['headers']['token'], TOKEN)
        self.assertEqual(len(cfg._parse_transactions(raw)), 1)

    def test_test_connection(self):
        bank = FakeBank(bal_pages=[[_balance(balanceOut='123.45')]])
        with patch(MOD + '.requests.get', side_effect=bank), \
                patch(MOD + '.sleep'):
            res = self.cfg.action_test_connection()
        self.assertEqual(res['params']['type'], 'success')
        self.assertIn('123.45', res['params']['message'])
        self.assertEqual(bank.calls[-1]['params']['acc'], IBAN)
        bank = FakeBank(bal_pages=[[]])
        with patch(MOD + '.requests.get', side_effect=bank), \
                patch(MOD + '.sleep'):
            res = self.cfg.action_test_connection()
        self.assertEqual(res['params']['type'], 'warning')
