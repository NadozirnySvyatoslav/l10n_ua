"""Тести провайдера ПУМБ Open Banking (мок API, справжні сертифікати)."""

import base64
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MODULE = 'odoo.addons.l10n_ua_bank_pumb.models.l10n_ua_bank_pumb_config'
OWN_IBAN = 'UA093348510000026200420671357'
OTHER_IBAN = 'UA113052990000026007891234567'


def _make_cert():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'TPP Test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert


def _response(status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b'{}' if json_data is not None else b''
    resp.text = str(json_data)
    resp.json.return_value = json_data
    return resp


def _txn(tid, amount, **extra):
    vals = {'transactionId': tid, 'bookingDate': '2026-09-01',
            'transactionAmount': {'amount': amount, 'currency': 'UAH'}}
    vals.update(extra)
    return vals


@tagged('post_install', '-at_install')
class TestPumb(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key, cls.cert = _make_cert()
        cls.cert_pem = cls.cert.public_bytes(serialization.Encoding.PEM)
        cls.key_pem = cls.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        partner = cls.env.company.partner_id
        bank_account = cls.env['res.partner.bank'].create({
            'acc_number': OWN_IBAN, 'partner_id': partner.id})
        uah = cls.env.ref('base.UAH')
        uah.active = True
        cls.journal = cls.env['account.journal'].create({
            'name': 'PUMB', 'type': 'bank', 'code': 'PUMB',
            'bank_account_id': bank_account.id, 'currency_id': uah.id,
            'company_id': cls.env.company.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'PUMB', 'provider': 'pumb',
            'journal_id': cls.journal.id,
            'pumb_environment': 'sandbox',
            'pumb_psu_id': OWN_IBAN,
            'pumb_cert_file': base64.b64encode(cls.cert_pem),
            'pumb_key_file': base64.b64encode(cls.key_pem),
        })

    def _set_valid_consent(self):
        self.config.write({
            'pumb_consent_id': 'consent-1234567890',
            'pumb_consent_status': 'valid',
            'pumb_consent_valid_to': date.today() + timedelta(days=30),
            'pumb_account_resource_id': 'acc-1',
        })

    def _patch(self, *responses):
        return patch('%s.requests.request' % MODULE, side_effect=list(responses))

    # --- сертифікат -----------------------------------------------------
    def test_pem_material_plain(self):
        cert, key = self.config._pumb_pem_material()
        self.assertEqual(cert, self.cert_pem)
        self.assertIn(b'PRIVATE KEY', key)

    def test_pem_material_encrypted_key(self):
        encrypted = self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b'secret'))
        self.config.write({'pumb_key_file': base64.b64encode(encrypted),
                           'pumb_key_password': 'secret'})
        _cert, key = self.config._pumb_pem_material()
        self.assertNotIn(b'ENCRYPTED', key)
        self.config.pumb_key_password = 'wrong'
        with self.assertRaises(UserError):
            self.config._pumb_pem_material()

    def test_pem_material_pkcs12(self):
        bundle = pkcs12.serialize_key_and_certificates(
            b'tpp', self.key, self.cert, None,
            serialization.BestAvailableEncryption(b'p12'))
        self.config.write({'pumb_cert_file': base64.b64encode(bundle),
                           'pumb_key_file': False, 'pumb_key_password': 'p12'})
        cert, key = self.config._pumb_pem_material()
        self.assertEqual(cert, self.cert_pem)
        self.assertIn(b'PRIVATE KEY', key)

    def test_pem_material_missing(self):
        self.config.pumb_key_file = False
        with self.assertRaises(UserError):
            self.config._pumb_pem_material()
        self.config.pumb_cert_file = False
        with self.assertRaises(UserError):
            self.config._pumb_pem_material()

    # --- згода -------------------------------------------------------------
    def test_consent_payload(self):
        self.config.pumb_frequency_per_day = 10
        payload = self.config._pumb_consent_payload()
        payment = payload['access']['payments'][0]
        self.assertEqual(payment['account'], {'iban': OWN_IBAN, 'currency': 'UAH'})
        self.assertEqual(payment['rights'],
                         ['balances', 'transactions', 'accountDetails'])
        self.assertEqual(payload['consentType'], 'detailed')
        self.assertEqual(payload['frequencyPerDay'], 4)
        self.assertEqual(payload['validTo'],
                         (date.today() + timedelta(days=90)).isoformat())

    def test_create_consent(self):
        with self._patch(
                _response(201, {'consentId': 'consent-1234567890',
                                'consentStatus': 'received',
                                'scaMethods': 'DECOUPLED'}),
                _response(201, {'authorisationId': 'auth-1',
                                'scaStatus': 'received',
                                'psuMessage': 'Підтвердіть у ПУМБ Online'}),
        ) as req:
            self.config.action_pumb_create_consent()
        create_call, auth_call = req.call_args_list
        self.assertEqual(create_call.args[:2], (
            'POST', 'https://open-api-sandbox.dts.fuib.com/psd2/openbanking/v2'
                    '/consents/account-access'))
        headers = create_call.kwargs['headers']
        self.assertEqual(headers['PSU-ID'], OWN_IBAN)
        self.assertEqual(headers['PSU-ID-Type'], 'IBAN')
        self.assertIn('X-Request-ID', headers)
        self.assertEqual(len(create_call.kwargs['cert']), 2)
        self.assertTrue(auth_call.args[1].endswith(
            '/consents/account-access/consent-1234567890/authorisations'))
        self.assertEqual(auth_call.kwargs['headers']['Target-Consent-State'], 'valid')
        self.assertEqual(self.config.pumb_consent_id, 'consent-1234567890')
        self.assertEqual(self.config.pumb_consent_status, 'received')
        self.assertEqual(self.config.pumb_authorisation_id, 'auth-1')
        self.assertEqual(self.config.pumb_psu_message, 'Підтвердіть у ПУМБ Online')

    def test_refresh_consent_fetches_account(self):
        self.config.write({'pumb_consent_id': 'consent-1234567890',
                           'pumb_consent_status': 'received',
                           'pumb_authorisation_id': 'auth-1'})
        with self._patch(
                _response(200, {'consentStatus': 'valid', 'validTo': '2026-12-01'}),
                _response(200, {'scaStatus': 'finalised'}),
                _response(200, {'accounts': [
                    {'resourceId': 'acc-9', 'iban': OTHER_IBAN},
                    {'resourceId': 'acc-7', 'iban': OWN_IBAN}]}),
        ) as req:
            self.config.action_pumb_refresh_consent()
        self.assertEqual(req.call_args_list[2].kwargs['headers']['Consent-ID'],
                         'consent-1234567890')
        self.assertEqual(self.config.pumb_consent_status, 'valid')
        self.assertEqual(self.config.pumb_consent_valid_to, date(2026, 12, 1))
        self.assertEqual(self.config.pumb_sca_status, 'finalised')
        self.assertEqual(self.config.pumb_account_resource_id, 'acc-7')

    def test_revoke_consent(self):
        self._set_valid_consent()
        with self._patch(_response(204)) as req:
            self.config.action_pumb_revoke_consent()
        self.assertEqual(req.call_args.args[0], 'DELETE')
        self.assertFalse(self.config.pumb_consent_id)
        self.assertEqual(self.config.pumb_consent_status, 'terminatedByTpp')

    def test_check_consent(self):
        with self.assertRaises(UserError):
            self.config._pumb_check_consent()
        self._set_valid_consent()
        self.config._pumb_check_consent()
        self.config.pumb_consent_status = 'received'
        with self.assertRaises(UserError):
            self.config._pumb_check_consent()
        self.config.write({'pumb_consent_status': 'valid',
                           'pumb_consent_valid_to': date.today() - timedelta(days=1)})
        with self.assertRaises(UserError):
            self.config._pumb_check_consent()

    def test_api_errors(self):
        self._set_valid_consent()
        expired = {'apiClientMessages': [{
            'category': 'ERROR', 'code': 'CONSENT_EXPIRED', 'path': '/accounts',
            'text': 'Consent expired'}]}
        with self._patch(_response(401, expired)):
            with self.assertRaisesRegex(UserError, 'CONSENT_EXPIRED'):
                self.config._pumb_request('GET', '/accounts')
        with self._patch(_response(429, {})):
            with self.assertRaises(UserError):
                self.config._pumb_request('GET', '/accounts')

    # --- виписка -----------------------------------------------------------
    def test_fetch_paginates(self):
        self._set_valid_consent()
        page1 = [_txn(str(i), 1.0) for i in range(100)]
        with self._patch(
                _response(200, {'account': {'iban': OWN_IBAN},
                                'transactions': {'booked': page1}}),
                _response(200, {'transactions': {'booked': [_txn('100', 2.0)]}}),
        ) as req:
            raw = self.config._fetch_from_bank(date(2026, 9, 1), date(2026, 9, 10))
        self.assertEqual(len(raw['booked']), 101)
        self.assertEqual(raw['iban'], OWN_IBAN)
        first, second = req.call_args_list
        self.assertTrue(first.args[1].endswith('/accounts/acc-1/transactions'))
        self.assertEqual(first.kwargs['headers']['Consent-ID'], 'consent-1234567890')
        self.assertEqual(first.kwargs['params']['bookingStatus'], 'booked')
        self.assertEqual(first.kwargs['params']['dateFrom'], '2026-09-01')
        self.assertEqual(first.kwargs['params']['offset'], 0)
        self.assertEqual(second.kwargs['params']['offset'], 100)

    def test_fetch_period_limit(self):
        self._set_valid_consent()
        with self.assertRaises(UserError):
            self.config._fetch_from_bank(date(2026, 7, 1), date(2026, 9, 1))

    def test_parse_directions(self):
        raw = {'iban': OWN_IBAN, 'booked': [
            # Надходження: платник — контрагент.
            _txn('t1', 2500.5, debtorAccount=OTHER_IBAN, creditorAccount=OWN_IBAN,
                 debtor={'name': 'ТОВ Клієнт'}, creditor={'name': 'Ми'},
                 remittanceInformationUnstructured='оплата за рахунком'),
            # Списання без знака: платник — наш рахунок.
            _txn('t2', 100.11, debtorAccount=OWN_IBAN, creditorAccount=OTHER_IBAN,
                 debtor={'name': 'Ми'}, creditor={'name': 'ТОВ Постачальник'}),
            # Списання зі знаком, карткова операція без bookingDate.
            {'transactionId': 29187195819,
             'transactionAmount': {'amount': -9.99, 'currency': 'UAH'},
             'cardTransaction': {'transactionDateTime': '2026-09-02T10:15:00Z'},
             'bankTransactionCodeProprietary': 'Покупка'},
            _txn('t0', 0),
        ]}
        txs = self.config._parse_transactions(raw)
        self.assertEqual(len(txs), 3)
        income, expense, card = txs
        self.assertEqual(income['amount'], 2500.5)
        self.assertEqual(income['partner_name'], 'ТОВ Клієнт')
        self.assertEqual(income['partner_iban'], OTHER_IBAN)
        self.assertEqual(income['description'], 'оплата за рахунком')
        self.assertEqual(expense['amount'], -100.11)
        self.assertEqual(expense['partner_name'], 'ТОВ Постачальник')
        self.assertEqual(expense['partner_iban'], OTHER_IBAN)
        self.assertEqual(card['id'], '29187195819')
        self.assertEqual(card['amount'], -9.99)
        self.assertEqual(card['date'], '2026-09-02')
        self.assertEqual(card['description'], 'Покупка')

    def test_amount_formats(self):
        amount = self.config._pumb_amount
        self.assertEqual(amount('5768,2'), 5768.2)
        self.assertEqual(amount('-1,50'), -1.5)
        self.assertEqual(amount('1 056'), 1056.0)
        self.assertEqual(amount(None), 0.0)

    def test_sync_job_creates_statement(self):
        self._set_valid_consent()
        booked = [
            _txn('j1', 1000.0, debtorAccount=OTHER_IBAN, creditorAccount=OWN_IBAN,
                 debtor={'name': 'ТОВ Клієнт'}),
            _txn('j2', -250.0, debtorAccount=OWN_IBAN, creditorAccount=OTHER_IBAN,
                 creditor={'name': 'ТОВ Постачальник'}),
        ]
        job = self.env['l10n_ua.bank.sync.job'].create({
            'config_id': self.config.id,
            'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 10)})
        with self._patch(_response(200, {'account': {'iban': OWN_IBAN},
                                         'transactions': {'booked': booked}})):
            job.action_fetch()
        self.assertEqual(job.state, 'done')
        self.assertEqual(job.imported_count, 2)
        lines = job.bank_statement_id.line_ids
        self.assertEqual(sorted(lines.mapped('amount')), [-250.0, 1000.0])
        self.assertEqual(set(lines.mapped('journal_id')), {self.journal})

    def test_non_pumb_delegates(self):
        other = self.env['l10n_ua.bank.sync.config'].create({
            'name': 'Manual', 'provider': 'manual', 'journal_id': self.journal.id})
        with self.assertRaises(NotImplementedError):
            other._parse_transactions({'booked': []})
