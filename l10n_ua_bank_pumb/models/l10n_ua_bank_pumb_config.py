import base64
import contextlib
import logging
import os
import tempfile
import uuid
from datetime import timedelta

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# ПУМБ Open Banking API (Berlin Group NextGenPSD2, v2).
PUMB_API_URLS = {
    'sandbox': 'https://open-api-sandbox.dts.fuib.com/psd2/openbanking/v2',
    'production': 'https://open-api.pumb.ua/psd2/openbanking/v2',
}
# Виписка — не більше 31 дня на запит.
PUMB_MAX_DAYS = 31
# Згода на доступ до рахунку — не більше 90 днів.
PUMB_CONSENT_MAX_DAYS = 90
# Не більше 4 звернень на добу без участі користувача (frequencyPerDay).
PUMB_MAX_FREQUENCY = 4
PUMB_CONSENT_CURRENCIES = ('UAH', 'USD', 'EUR', 'GBP', 'PLN')
PUMB_CONSENT_RIGHTS = ['balances', 'transactions', 'accountDetails']
# Пагінація виписки: limit/offset; запобіжник від нескінченного циклу.
PUMB_PAGE_LIMIT = 100
PUMB_MAX_PAGES = 50
# Коди помилок, після яких потрібна нова згода.
PUMB_CONSENT_ERRORS = ('CONSENT_UNKNOWN', 'CONSENT_INVALID', 'CONSENT_EXPIRED')

CONSENT_STATUSES = [
    ('received', 'Received (awaiting confirmation)'),
    ('rejected', 'Rejected'),
    ('partiallyAuthorised', 'Partially Authorised'),
    ('valid', 'Valid'),
    ('expired', 'Expired'),
    ('revokedByPsu', 'Revoked by Client'),
    ('terminatedByTpp', 'Terminated'),
    ('replacedByTpp', 'Replaced'),
]
SCA_STATUSES = [
    ('started', 'Started'),
    ('received', 'Received'),
    ('psuIdentified', 'Client Identified'),
    ('finalised', 'Finalised'),
    ('failed', 'Failed'),
]


class L10nUaBankSyncConfig(models.Model):
    """Провайдер ПУМБ: виписки через Open Banking API (NextGenPSD2).

    Доступ до рахунку дає згода (consent) клієнта: створюємо її, стартуємо
    авторизацію (SCA DECOUPLED — клієнт підтверджує в застосунку ПУМБ Online),
    далі за Consent-ID читаємо рахунки та операції. Автентифікація TPP — mTLS
    із сертифікатом відкритого банкінгу (QWAC).
    """
    _inherit = 'l10n_ua.bank.sync.config'

    provider = fields.Selection(
        selection_add=[('pumb', 'PUMB (Open Banking)')],
        ondelete={'pumb': 'set default'},
    )

    pumb_environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        string='PUMB Environment',
        default='sandbox',
        help='Sandbox works with PUMB test key pairs and test IBANs; '
             'production requires a QWAC certificate of a registered TPP.',
    )

    # mTLS: сертифікат відкритого банкінгу (QWAC) + приватний ключ.
    pumb_cert_file = fields.Binary(
        string='Client Certificate',
        attachment=True,
        groups='l10n_ua_account_base.group_ua_manager',
        help='QWAC certificate for mTLS: PEM/DER, or a PKCS#12 bundle '
             '(.p12/.pfx) that already contains the private key.',
    )
    pumb_cert_filename = fields.Char(string='Certificate File Name')
    pumb_key_file = fields.Binary(
        string='Private Key',
        attachment=True,
        groups='l10n_ua_account_base.group_ua_manager',
        help='Private key of the certificate (PEM/DER). Not needed for '
             'PKCS#12 or when the PEM certificate file includes the key.',
    )
    pumb_key_filename = fields.Char(string='Private Key File Name')
    pumb_key_password = fields.Char(
        string='Key Password',
        groups='l10n_ua_account_base.group_ua_manager',
        help='Password of an encrypted private key or of a PKCS#12 bundle.',
    )

    # Ідентифікація користувача (PSU).
    pumb_psu_id_type = fields.Selection(
        [('IBAN', 'IBAN'), ('LOGIN', 'Login')],
        string='PSU ID Type',
        default='IBAN',
    )
    pumb_psu_id = fields.Char(
        string='PSU ID',
        help='Client identifier in PUMB: account IBAN or PUMB Online login.',
    )
    pumb_corporate_id = fields.Char(
        string='Corporate IBAN',
        help='Required for legal entities: IBAN of the corporate client '
             '(PSU-Corporate-ID).',
    )
    pumb_account_iban = fields.Char(
        string='Account IBAN',
        help='IBAN of the account to import. Defaults to the bank account '
             'of the journal.',
    )

    # Параметри згоди.
    pumb_consent_days = fields.Integer(
        string='Consent Validity (days)',
        default=PUMB_CONSENT_MAX_DAYS,
        help='Up to 90 days, after that the client must confirm a new consent.',
    )
    pumb_frequency_per_day = fields.Integer(
        string='Requests per Day',
        default=PUMB_MAX_FREQUENCY,
        help='Maximum number of account accesses per day without the client '
             '(1-4). Every statement page and every accounts request counts.',
    )
    pumb_sandbox_consent_state = fields.Selection(
        [('valid', 'Confirmed'), ('rejected', 'Rejected')],
        string='Sandbox Result',
        default='valid',
        help='Sandbox only: consent state the test bank sets instead of '
             'waiting for confirmation in PUMB Online.',
    )

    # Стан згоди (заповнюється з API).
    pumb_consent_id = fields.Char(string='Consent ID', readonly=True, copy=False)
    pumb_consent_status = fields.Selection(
        CONSENT_STATUSES, string='Consent Status', readonly=True, copy=False)
    pumb_consent_valid_to = fields.Date(
        string='Consent Valid To', readonly=True, copy=False)
    pumb_authorisation_id = fields.Char(
        string='Authorisation ID', readonly=True, copy=False)
    pumb_sca_status = fields.Selection(
        SCA_STATUSES, string='Confirmation Status', readonly=True, copy=False)
    pumb_psu_message = fields.Char(
        string='Bank Message', readonly=True, copy=False)
    pumb_account_resource_id = fields.Char(
        string='Account Resource ID', readonly=True, copy=False,
        help='Account identifier in PUMB Open Banking, received after the '
             'consent is confirmed.')

    # ------------------------------------------------------------------
    # Параметри запиту
    # ------------------------------------------------------------------
    @staticmethod
    def _pumb_norm_iban(value):
        return (value or '').replace(' ', '').upper()

    def _pumb_iban(self):
        self.ensure_one()
        return self._pumb_norm_iban(
            self.pumb_account_iban or self.bank_account_id.acc_number)

    def _pumb_currency(self):
        self.ensure_one()
        return (self.journal_id.currency_id or self.company_id.currency_id).name

    def _pumb_base_url(self):
        self.ensure_one()
        return PUMB_API_URLS[self.pumb_environment or 'sandbox']

    @staticmethod
    def _pumb_psu_ip():
        """IP користувача для PSU-IP-Address (у cron запиту немає)."""
        if request:
            return request.httprequest.remote_addr or '127.0.0.1'
        return '127.0.0.1'

    def _pumb_psu_headers(self):
        """Заголовки ідентифікації користувача — для створення згоди."""
        self.ensure_one()
        if not self.pumb_psu_id:
            raise UserError(_('Fill in PSU ID (account IBAN or PUMB Online login).'))
        headers = {
            'PSU-ID': self.pumb_psu_id.strip(),
            'PSU-ID-Type': self.pumb_psu_id_type or 'IBAN',
            'PSU-IP-Address': self._pumb_psu_ip(),
        }
        if self.pumb_corporate_id:
            headers['PSU-Corporate-ID'] = self._pumb_norm_iban(self.pumb_corporate_id)
            headers['PSU-Corporate-ID-Type'] = 'IBAN'
        return headers

    # ------------------------------------------------------------------
    # mTLS: сертифікат і ключ
    # ------------------------------------------------------------------
    def _pumb_pem_material(self):
        """(cert_pem, key_pem) з завантажених файлів; ключ — без пароля.

        requests приймає лише незашифрований PEM, тому PKCS#12, DER і
        зашифровані ключі розпаковуємо через cryptography.
        """
        self.ensure_one()
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import pkcs12

        record = self.sudo()
        if not record.pumb_cert_file:
            raise UserError(_('Upload the PUMB client certificate (QWAC).'))
        cert_data = base64.b64decode(record.pumb_cert_file)
        key_data = (base64.b64decode(record.pumb_key_file)
                    if record.pumb_key_file else b'')
        password = (record.pumb_key_password or '').encode() or None

        def key_to_pem(key):
            return key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption())

        try:
            if b'-----BEGIN' not in cert_data:
                try:
                    cert = x509.load_der_x509_certificate(cert_data)
                except ValueError:
                    key, cert, extra = pkcs12.load_key_and_certificates(
                        cert_data, password)
                    if not (key and cert):
                        raise UserError(_(
                            'The PKCS#12 file has no certificate or private key.'))
                    chain = b''.join(
                        c.public_bytes(serialization.Encoding.PEM)
                        for c in [cert] + list(extra or []))
                    return chain, key_to_pem(key)
                cert_data = cert.public_bytes(serialization.Encoding.PEM)
            if not key_data and b'PRIVATE KEY-----' in cert_data:
                key_data = cert_data
            if not key_data:
                raise UserError(_('Upload the private key of the certificate.'))
            if b'-----BEGIN' in key_data:
                key = serialization.load_pem_private_key(key_data, password)
            else:
                key = serialization.load_der_private_key(key_data, password)
        except (ValueError, TypeError) as e:
            raise UserError(_(
                'Cannot read the certificate or private key: %s') % e) from e
        return cert_data, key_to_pem(key)

    @contextlib.contextmanager
    def _pumb_client_cert(self):
        """Тимчасові файли (cert, key) для requests; видаляються після запиту."""
        cert_pem, key_pem = self._pumb_pem_material()
        with tempfile.TemporaryDirectory(prefix='pumb_') as tmp:
            paths = []
            for name, data in (('cert.pem', cert_pem), ('key.pem', key_pem)):
                path = os.path.join(tmp, name)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
                with os.fdopen(fd, 'wb') as fh:
                    fh.write(data)
                paths.append(path)
            yield tuple(paths)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    @staticmethod
    def _pumb_error_text(response):
        """Текст помилки з ResponseClientMessages (apiClientMessages[])."""
        try:
            data = response.json()
        except ValueError:
            return response.text[:500], []
        messages = (data or {}).get('apiClientMessages') or []
        codes = [m.get('code') for m in messages if m.get('code')]
        text = '; '.join(
            '%s: %s' % (m.get('code', ''), m.get('text', '')) for m in messages)
        return text or response.text[:500], codes

    def _pumb_request(self, method, path, headers=None, params=None, payload=None):
        """Запит до ПУМБ Open Banking з mTLS і новим X-Request-ID."""
        self.ensure_one()
        url = self._pumb_base_url() + path
        all_headers = {
            'X-Request-ID': str(uuid.uuid4()),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        all_headers.update(headers or {})
        _logger.info('PUMB: %s %s %s', method, path, params or '')
        with self._pumb_client_cert() as cert:
            try:
                response = requests.request(
                    method, url, headers=all_headers, params=params,
                    json=payload, cert=cert, timeout=60)
            except requests.exceptions.RequestException as e:
                raise UserError(_('Connection to PUMB failed: %s') % e) from e
        _logger.info('PUMB: response %s (X-Request-ID %s)',
                     response.status_code, all_headers['X-Request-ID'])

        if response.status_code == 429:
            raise UserError(_(
                'PUMB request limit exceeded (up to %d requests per day per '
                'consent). Try again tomorrow.') % PUMB_MAX_FREQUENCY)
        if response.status_code >= 400:
            text, codes = self._pumb_error_text(response)
            if set(codes) & set(PUMB_CONSENT_ERRORS):
                raise UserError(_(
                    'PUMB consent is not valid (%s). Create a new consent and '
                    'confirm it in PUMB Online.') % text)
            raise UserError(_('PUMB API error %(status)s: %(text)s') % {
                'status': response.status_code, 'text': text})
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _pumb_consent_headers(self):
        self.ensure_one()
        return {'Consent-ID': self.pumb_consent_id}

    # ------------------------------------------------------------------
    # Згода (consent) на доступ до рахунку
    # ------------------------------------------------------------------
    def _pumb_consent_payload(self):
        self.ensure_one()
        iban = self._pumb_iban()
        if not iban:
            raise UserError(_(
                'Fill in Account IBAN or set a bank account on the journal.'))
        currency = self._pumb_currency()
        if currency not in PUMB_CONSENT_CURRENCIES:
            raise UserError(_(
                'PUMB Open Banking does not support account currency %s.')
                % currency)
        days = min(max(self.pumb_consent_days or PUMB_CONSENT_MAX_DAYS, 1),
                   PUMB_CONSENT_MAX_DAYS)
        frequency = min(max(self.pumb_frequency_per_day or PUMB_MAX_FREQUENCY, 1),
                        PUMB_MAX_FREQUENCY)
        valid_to = fields.Date.context_today(self) + timedelta(days=days)
        return {
            'access': {
                'payments': [{
                    'account': {'iban': iban, 'currency': currency},
                    'rights': PUMB_CONSENT_RIGHTS,
                }],
            },
            'consentType': 'detailed',
            'recurringIndicator': 'true',
            'validTo': valid_to.isoformat(),
            'frequencyPerDay': frequency,
        }

    def action_pumb_create_consent(self):
        """Створити згоду і стартувати її підтвердження в ПУМБ Online."""
        self.ensure_one()
        payload = self._pumb_consent_payload()
        consent = self._pumb_request(
            'POST', '/consents/account-access',
            headers=self._pumb_psu_headers(), payload=payload)
        consent_id = consent.get('consentId')
        if not consent_id:
            raise UserError(_('PUMB did not return a consent ID.'))

        auth_headers = {'PSU-IP-Address': self._pumb_psu_ip()}
        if self.pumb_environment == 'sandbox' and self.pumb_sandbox_consent_state:
            auth_headers['Target-Consent-State'] = self.pumb_sandbox_consent_state
        auth = self._pumb_request(
            'POST', '/consents/account-access/%s/authorisations' % consent_id,
            headers=auth_headers)

        message = (auth.get('psuMessage') or consent.get('psuMessage')
                   or _('Confirm the consent in the PUMB Online app, then '
                        'press "Refresh Consent".'))
        self.write({
            'pumb_consent_id': consent_id,
            'pumb_consent_status': consent.get('consentStatus') or 'received',
            'pumb_consent_valid_to': payload['validTo'],
            'pumb_authorisation_id': auth.get('authorisationId') or False,
            'pumb_sca_status': auth.get('scaStatus') or False,
            'pumb_psu_message': message,
            'pumb_account_resource_id': False,
        })
        return self._pumb_notify(_('Consent created'), message, 'info', sticky=True)

    def action_pumb_refresh_consent(self):
        """Оновити статус згоди; після підтвердження — отримати ID рахунку."""
        self.ensure_one()
        self._pumb_refresh_consent()
        if self.pumb_consent_status == 'valid' and not self.pumb_account_resource_id:
            self._pumb_fetch_account_resource_id()
        status = dict(CONSENT_STATUSES).get(
            self.pumb_consent_status, self.pumb_consent_status or '')
        return self._pumb_notify(
            _('PUMB consent'),
            _('Consent status: %(status)s, valid to %(date)s.') % {
                'status': status, 'date': self.pumb_consent_valid_to or '-'},
            'success' if self.pumb_consent_status == 'valid' else 'warning')

    def _pumb_refresh_consent(self):
        self.ensure_one()
        if not self.pumb_consent_id:
            raise UserError(_('No PUMB consent yet: press "Create Consent".'))
        consent = self._pumb_request(
            'GET', '/consents/account-access/%s' % self.pumb_consent_id)
        vals = {'pumb_consent_status': consent.get('consentStatus') or False}
        if consent.get('validTo'):
            vals['pumb_consent_valid_to'] = consent['validTo'][:10]
        if self.pumb_authorisation_id:
            sca = self._pumb_request(
                'GET', '/consents/%s/authorisations/%s' % (
                    self.pumb_consent_id, self.pumb_authorisation_id))
            vals['pumb_sca_status'] = sca.get('scaStatus') or False
        self.write(vals)

    def _pumb_fetch_account_resource_id(self):
        """Знайти resourceId рахунку за IBAN серед рахунків згоди."""
        self.ensure_one()
        data = self._pumb_request(
            'GET', '/accounts', headers=self._pumb_consent_headers())
        iban = self._pumb_iban()
        accounts = data.get('accounts') or []
        account = next(
            (a for a in accounts
             if self._pumb_norm_iban(a.get('iban')) == iban), None)
        if not account:
            raise UserError(_(
                'Account %(iban)s is not among the consent accounts: %(list)s')
                % {'iban': iban,
                   'list': ', '.join(a.get('iban', '') for a in accounts) or '-'})
        self.pumb_account_resource_id = account.get('resourceId')
        return self.pumb_account_resource_id

    def action_pumb_revoke_consent(self):
        """Відкликати згоду в банку та очистити її дані."""
        self.ensure_one()
        if self.pumb_consent_id:
            self._pumb_request(
                'DELETE', '/consents/account-access/%s' % self.pumb_consent_id)
        self.write({
            'pumb_consent_id': False,
            'pumb_consent_status': 'terminatedByTpp',
            'pumb_consent_valid_to': False,
            'pumb_authorisation_id': False,
            'pumb_sca_status': False,
            'pumb_psu_message': False,
            'pumb_account_resource_id': False,
        })
        return self._pumb_notify(
            _('PUMB consent'), _('Consent revoked.'), 'success')

    def _pumb_check_consent(self):
        """Згода є, підтверджена і не прострочена."""
        self.ensure_one()
        if not self.pumb_consent_id:
            raise UserError(_('No PUMB consent yet: press "Create Consent".'))
        if self.pumb_consent_status != 'valid':
            raise UserError(_(
                'PUMB consent is not confirmed (status: %s). Confirm it in '
                'PUMB Online and press "Refresh Consent".')
                % (self.pumb_consent_status or '-'))
        today = fields.Date.context_today(self)
        if self.pumb_consent_valid_to and self.pumb_consent_valid_to < today:
            raise UserError(_(
                'PUMB consent expired on %s. Create a new consent.')
                % self.pumb_consent_valid_to)

    @staticmethod
    def _pumb_notify(title, message, kind, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': kind,
                'sticky': sticky,
            },
        }

    # ------------------------------------------------------------------
    # Виписка
    # ------------------------------------------------------------------
    def _fetch_from_bank(self, date_from, date_to):
        """Проведені операції рахунку за період (з пагінацією)."""
        self.ensure_one()

        if self.provider != 'pumb':
            return super()._fetch_from_bank(date_from, date_to)

        if (date_to - date_from).days > PUMB_MAX_DAYS:
            raise UserError(_(
                'PUMB API allows maximum %d days per request.') % PUMB_MAX_DAYS)
        if self.pumb_consent_id and self.pumb_consent_status in (
                'received', 'partiallyAuthorised'):
            # Клієнт міг уже підтвердити згоду в ПУМБ Online.
            self._pumb_refresh_consent()
        self._pumb_check_consent()
        resource_id = (self.pumb_account_resource_id
                       or self._pumb_fetch_account_resource_id())

        path = '/accounts/%s/transactions' % resource_id
        booked = []
        account = {}
        for page in range(PUMB_MAX_PAGES):
            data = self._pumb_request(
                'GET', path, headers=self._pumb_consent_headers(), params={
                    'dateFrom': date_from.isoformat(),
                    'dateTo': date_to.isoformat(),
                    'bookingStatus': 'booked',
                    'limit': PUMB_PAGE_LIMIT,
                    'offset': page * PUMB_PAGE_LIMIT,
                })
            account = account or data.get('account') or {}
            items = (data.get('transactions') or {}).get('booked') or []
            booked.extend(items)
            if len(items) < PUMB_PAGE_LIMIT:
                break
        else:
            _logger.warning('PUMB: stopped after %d statement pages', PUMB_MAX_PAGES)

        return {
            'api_type': 'transactions',
            'account_resource_id': resource_id,
            'iban': self._pumb_norm_iban(account.get('iban')) or self._pumb_iban(),
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'booked': booked,
        }

    @staticmethod
    def _pumb_amount(value):
        """Сума: число або рядок ('5768,2', '-1,50', '1 056')."""
        if isinstance(value, (int, float)):
            return float(value)
        text = (str(value or '0').replace(' ', '').replace('\xa0', '')
                .replace(',', '.'))
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _parse_transactions(self, raw_data):
        """Операції ПУМБ → словники транзакцій (Кт +, Дт −)."""
        self.ensure_one()

        if self.provider != 'pumb':
            return super()._parse_transactions(raw_data)

        own_iban = self._pumb_norm_iban((raw_data or {}).get('iban'))
        transactions = []
        for txn in (raw_data or {}).get('booked') or []:
            amount = self._pumb_amount(
                (txn.get('transactionAmount') or {}).get('amount'))
            if not amount:
                continue
            debtor_iban = self._pumb_norm_iban(txn.get('debtorAccount'))
            creditor_iban = self._pumb_norm_iban(txn.get('creditorAccount'))
            # Сума може приходити без знака: напрям визначаємо за тим, чий
            # рахунок у ролі платника (debtorAccount).
            outgoing = amount < 0 or (
                own_iban and debtor_iban == own_iban and creditor_iban != own_iban)
            if outgoing:
                partner = txn.get('creditor') or {}
                partner_iban = creditor_iban
            else:
                partner = txn.get('debtor') or {}
                partner_iban = debtor_iban
            date = txn.get('bookingDate') or (
                (txn.get('cardTransaction') or {}).get('transactionDateTime') or '')
            transactions.append({
                'id': str(txn.get('transactionId') or ''),
                'date': date[:10],
                'amount': -abs(amount) if outgoing else abs(amount),
                'description': (txn.get('remittanceInformationUnstructured')
                                or txn.get('additionalTransactionInformation')
                                or txn.get('bankTransactionCodeProprietary')
                                or ''),
                'partner_name': partner.get('name') or '',
                'partner_iban': partner_iban,
                'partner_edrpou': '',
            })
        return transactions

    def action_test_connection(self):
        """Перевірити mTLS-з'єднання і стан згоди (без читання рахунку)."""
        self.ensure_one()

        if self.provider != 'pumb':
            return super().action_test_connection()

        if not self.pumb_consent_id:
            # Без згоди перевіряємо лише сертифікат і ключ.
            self._pumb_pem_material()
            return self._pumb_notify(
                _('Success'),
                _('Certificate and key are valid. Now press "Create Consent".'),
                'success')
        return self.action_pumb_refresh_consent()
