import logging
import re
import requests
from datetime import date, datetime, time, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Personal API (individuals and individual entrepreneurs):
# https://api.monobank.ua/docs/index.html
MONO_API_URL = "https://api.monobank.ua"
# The longest span one personal statement request may cover: 31 days and
# one hour (2 682 000 seconds), per the documentation.
MONO_PERSONAL_MAX_SPAN = 31 * 86400 + 3600
# Each personal API function may be called once in 60 seconds.
MONO_PERSONAL_RATE_WAIT = 60
# A personal statement page holds up to 500 operations, newest first; a full
# page means there may be more before the oldest one received.
MONO_PERSONAL_PAGE_SIZE = 500
# Every further page costs a 60-second wait, and a request must finish within
# Odoo's real-time limit: two pages is the most one sync sits out.
MONO_PERSONAL_MAX_PAGES = 2
# The longest one personal sync sits out the rate limit, in seconds.
MONO_PERSONAL_MAX_WAIT = 60

# Corporate API for legal entities: https://corp-api.monobank.ua/
MONO_CORP_API_URL = "https://corp-api.monobank.ua"
# The corporate statement returns 10 items unless asked for more; 500 is the cap.
MONO_CORP_PAGE_SIZE = 500
# A runaway loop guard: 200 pages is 100 000 operations in one period.
MONO_CORP_MAX_PAGES = 200
# How far before the period start operations are asked for, so that one
# created earlier and booked inside the period is not missed.
MONO_CORP_LOOKBACK_DAYS = 7
# The longest span one statement request may cover.
MONO_CORP_WINDOW_DAYS = 31
# The longest a request sits out the rate limit before giving up, in seconds.
MONO_CORP_MAX_RATE_WAIT = 120
IBAN_UA_RE = re.compile(r'^UA\d{27}$')
KYIV_TZ = ZoneInfo('Europe/Kyiv')


def _clean_iban(value):
    return (value or '').replace(' ', '').upper()


def _kyiv_bounds(date_from, date_to):
    """Unix bounds of the Kyiv days [date_from, date_to], whatever the
    server's timezone is: the bank's day is the Kyiv one."""
    return (int(datetime.combine(date_from, time.min, tzinfo=KYIV_TZ).timestamp()),
            int(datetime.combine(date_to, time.max, tzinfo=KYIV_TZ).timestamp()))


def _kyiv_date(ts):
    return datetime.fromtimestamp(ts, KYIV_TZ).strftime('%Y-%m-%d') if ts else ''


class L10nUaBankSyncConfig(models.Model):
    """Extend base config with monobank provider."""
    _inherit = 'l10n_ua.bank.sync.config'

    provider = fields.Selection(
        selection_add=[('mono', 'monobank')],
        ondelete={'mono': 'set default'},
    )

    mono_api_type = fields.Selection(
        [
            ('personal', 'Personal API (individual entrepreneur)'),
            ('corporate', 'Corporate API (legal entity)'),
        ],
        string='API Type',
        default='personal',
        tracking=True,
        help='Personal API (api.monobank.ua) serves individuals and individual '
             'entrepreneurs, with a token from the monobank app. Corporate API '
             '(corp-api.monobank.ua) serves legal entities, with a token issued '
             'for the company in the monobank web cabinet.',
    )

    # The token gives full read access to the accounts (and, on the corporate
    # API, prepares payments): only managers see it. The sync itself reads it
    # with sudo, so an accountant can still run a sync.
    mono_api_token = fields.Char(
        string='API Token',
        groups='l10n_ua_account_base.group_ua_manager',
        help='Personal API: token from monobank settings (Настройки → API). '
             'Corporate API: company token from web.monobank.ua.',
    )
    mono_has_token = fields.Boolean(
        string='Has API Token',
        compute='_compute_mono_has_token',
    )
    mono_account_id = fields.Char(
        string='Account ID',
        help='Personal API: monobank account ID (optional: found by the IBAN '
             'of the journal bank account). Corporate API: account IBAN '
             '(optional, the IBAN of the journal bank account is used by '
             'default).',
    )

    def _compute_mono_has_token(self):
        for record, sudo_record in zip(self, self.sudo()):
            record.mono_has_token = bool(sudo_record.mono_api_token)

    def _mono_token(self):
        self.ensure_one()
        token = self.sudo().mono_api_token
        if not token:
            raise UserError(_("Please configure monobank API Token"))
        return token

    def _mono_journal_iban(self):
        self.ensure_one()
        return _clean_iban(self.bank_account_id.acc_number)

    def _fetch_from_bank(self, date_from, date_to):
        """Fetch statements from monobank API."""
        self.ensure_one()

        if self.provider != 'mono':
            return super()._fetch_from_bank(date_from, date_to)

        self._mono_token()

        if self.mono_api_type == 'corporate':
            return self._mono_corp_fetch_statement(date_from, date_to)
        return self._mono_personal_fetch_statement(date_from, date_to)

    def _parse_transactions(self, raw_data):
        """Parse monobank API response into transaction list."""
        self.ensure_one()

        if self.provider != 'mono':
            return super()._parse_transactions(raw_data)

        if raw_data.get('api_type') == 'corp_statement':
            return self._mono_corp_parse(raw_data)
        return self._mono_personal_parse(raw_data)

    def _extract_balances(self, raw_data):
        if self.provider != 'mono':
            return super()._extract_balances(raw_data)
        if raw_data.get('api_type') == 'corp_statement':
            return self._mono_corp_balances(raw_data)
        return self._mono_personal_balances(raw_data)

    def _statement_line_vals(self, trans):
        vals = super()._statement_line_vals(trans)
        if self.provider == 'mono':
            vals.update({
                'l10n_ua_mono_receipt_id': trans.get('receipt_id') or False,
                'l10n_ua_mono_external_ref': trans.get('external_reference') or False,
            })
        return vals

    def action_test_connection(self):
        """Test monobank API connection."""
        self.ensure_one()

        if self.provider != 'mono':
            return super().action_test_connection()

        self._mono_token()

        if self.mono_api_type == 'corporate':
            return self._mono_corp_test_connection()

        data = self._mono_personal_request('/personal/client-info')
        client_name = data.get('name', 'Unknown')
        accounts = self._mono_personal_accounts(data)
        iban = self._mono_journal_iban()
        if iban and iban not in [_clean_iban(acc.get('iban')) for acc in accounts]:
            message = _(
                "Connected to monobank, but account %(iban)s is not among the "
                "%(count)d accounts of %(client)s.",
                iban=iban, count=len(accounts), client=client_name)
            kind = 'warning'
        else:
            message = _('Connected to monobank. Client: %s, Accounts: %d') % (
                client_name, len(accounts))
            kind = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success') if kind == 'success' else _('Warning'),
                'message': message,
                'type': kind,
            }
        }

    def action_fetch_accounts(self):
        """Fetch available accounts from monobank."""
        self.ensure_one()

        self._mono_token()

        if self.mono_api_type == 'corporate':
            return self._mono_corp_fetch_accounts()

        data = self._mono_personal_request('/personal/client-info')

        # Format account list for display
        account_info = []
        for acc in self._mono_personal_accounts(data):
            currency = acc.get('currencyCode', 0)
            currency_name = self._mono_corp_currency_name(currency)
            balance = (acc.get('balance') or 0) / 100.0
            account_info.append(
                f"ID: {acc.get('id')} | {acc.get('iban') or ''} | "
                f"{currency_name} | Balance: {balance:.2f}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Available Accounts'),
                'message': '\n'.join(account_info) or _('No accounts found'),
                'type': 'info',
                'sticky': True,
            }
        }

    # --- Personal API (individuals, individual entrepreneurs) ---

    def _mono_wait(self, budget, seconds):
        """Sit out `seconds` of the personal rate limit, within the budget
        one sync may spend waiting; past it, say when to try again."""
        if budget['waited'] + seconds > MONO_PERSONAL_MAX_WAIT:
            raise UserError(_(
                "monobank API rate limit: one request per %s seconds. Retry "
                "in %s seconds, or shorten the period.") % (
                    MONO_PERSONAL_RATE_WAIT, seconds))
        _logger.info("monobank: rate limited, waiting %ss", seconds)
        sleep(seconds)
        budget['waited'] += seconds

    def _mono_personal_request(self, path, budget=None):
        """GET a personal API resource and return its decoded JSON."""
        self.ensure_one()
        budget = budget if budget is not None else {'waited': 0}
        headers = {'X-Token': self._mono_token()}
        while True:
            try:
                response = requests.get(
                    f"{MONO_API_URL}{path}", headers=headers, timeout=60)
            except requests.exceptions.RequestException as e:
                raise UserError(_("Connection failed: %s") % str(e))
            _logger.info("monobank: %s -> %s", path, response.status_code)
            if response.status_code != 429:
                break
            # The personal API documents a fixed limit of one call per 60
            # seconds per function, without a retry-after header.
            self._mono_wait(budget, MONO_PERSONAL_RATE_WAIT)

        if response.status_code != 200:
            try:
                message = response.json().get('errorDescription')
            except (ValueError, AttributeError):
                message = None
            raise UserError(_("monobank API error: %s") % (message or response.text))
        return response.json()

    @staticmethod
    def _mono_personal_accounts(client_info):
        """Own accounts and the FOP accounts shared with an accountant."""
        accounts = list(client_info.get('accounts') or [])
        for client in client_info.get('managedClients') or []:
            accounts.extend(client.get('accounts') or [])
        return accounts

    def _mono_personal_account(self, budget):
        """The account to read: set explicitly, or the one whose IBAN is the
        journal's. Picking "the first UAH account" would import another
        account's operations into this journal without a word."""
        self.ensure_one()
        if self.mono_account_id:
            return self.mono_account_id
        iban = self._mono_journal_iban()
        if not iban:
            raise UserError(_(
                "Set a bank account (IBAN) on the journal, or the monobank "
                "account ID, to read the statement."))
        data = self._mono_personal_request('/personal/client-info', budget)
        accounts = self._mono_personal_accounts(data)
        for acc in accounts:
            if _clean_iban(acc.get('iban')) == iban and acc.get('id'):
                # Remembered, so later syncs skip client-info and its own
                # 60-second limit.
                self.sudo().mono_account_id = acc['id']
                return acc['id']
        raise UserError(_(
            "monobank has no account %(iban)s for this token. Available: "
            "%(ibans)s",
            iban=iban,
            ibans=', '.join(filter(None, (acc.get('iban') for acc in accounts)))
            or _('none')))

    def _mono_personal_fetch_statement(self, date_from, date_to):
        """Read every operation of the Kyiv days [date_from, date_to].

        A page holds at most 500 operations, newest first, counting back from
        `to`. A full page means there may be more: the next request ends at
        the time of the oldest one received; the ones sharing its second come
        again and are dropped by id.
        """
        from_ts, to_ts = _kyiv_bounds(date_from, date_to)
        if to_ts - from_ts + 1 > MONO_PERSONAL_MAX_SPAN:
            raise UserError(_(
                "monobank API allows maximum 31 days per request"))
        budget = {'waited': 0}
        account_id = self._mono_personal_account(budget)

        items, seen = [], set()
        high = to_ts
        for page_no in range(MONO_PERSONAL_MAX_PAGES):
            if page_no:
                self._mono_wait(budget, MONO_PERSONAL_RATE_WAIT)
            page = self._mono_personal_request(
                f"/personal/statement/{account_id}/{from_ts}/{high}", budget)
            if not isinstance(page, list):
                raise UserError(_("monobank API error: %s") % page)
            new = [item for item in page if item.get('id') not in seen]
            for item in new:
                seen.add(item.get('id'))
                items.append(item)
            if len(page) < MONO_PERSONAL_PAGE_SIZE:
                break
            if not new:
                raise UserError(_(
                    "monobank statement for %s has more than %s operations "
                    "within one second and cannot be read page by page."
                ) % (account_id, MONO_PERSONAL_PAGE_SIZE))
            high = min(item.get('time') or high for item in page)
        else:
            raise UserError(_(
                "monobank statement for %(account)s has more than %(count)s "
                "operations in the period; shorten it.",
                account=account_id,
                count=MONO_PERSONAL_PAGE_SIZE * MONO_PERSONAL_MAX_PAGES))

        return {
            'api_type': 'statement',
            'account_id': account_id,
            'from_ts': from_ts,
            'to_ts': to_ts,
            'response': items,
        }

    def _mono_personal_parse(self, raw_data):
        items = raw_data.get('response', [])
        if not isinstance(items, list):
            return []
        transactions = []
        for item in items:
            transactions.append({
                'id': item.get('id', ''),
                'date': _kyiv_date(item.get('time')),
                # Signed kopecks: positive is incoming, negative outgoing.
                'amount': (item.get('amount') or 0) / 100.0,
                'description': item.get('description', ''),
                'partner_name': item.get('counterName', ''),
                'partner_iban': item.get('counterIban', ''),
                'partner_edrpou': item.get('counterEdrpou', ''),
                'receipt_id': item.get('receiptId', ''),
            })
        return transactions

    def _mono_personal_balances(self, raw_data):
        """Opening and closing balances from the operations themselves: each
        carries the account balance after it. The list runs newest first."""
        items = raw_data.get('response')
        if not isinstance(items, list) or not items:
            return (None, None)
        times = [item.get('time') or 0 for item in items]
        if times != sorted(times, reverse=True) or any(
                item.get('balance') is None for item in (items[0], items[-1])):
            return (None, None)
        oldest, newest = items[-1], items[0]
        opening = (oldest['balance'] - (oldest.get('amount') or 0)) / 100.0
        return (round(opening, 2), round(newest['balance'] / 100.0, 2))

    # --- Corporate API (legal entities) ---

    def _mono_corp_request(self, path, params=None):
        """GET a Corporate API resource and return its decoded JSON."""
        self.ensure_one()
        url = f"{MONO_CORP_API_URL}{path}"
        headers = {
            'x-token': self._mono_token(),
            'accept': 'application/json',
        }
        waited = 0
        while True:
            try:
                response = requests.get(url, headers=headers, params=params, timeout=60)
            except requests.exceptions.RequestException as e:
                raise UserError(_("Connection failed: %s") % str(e))

            _logger.info("monobank corporate: %s -> %s", path, response.status_code)

            if response.status_code != 429:
                break
            # Limits are per company, and the bank says when the next call may
            # go. A statement takes several calls, so a short wait is sat out
            # rather than failing the whole period; a long one is reported.
            try:
                retry_after = int(response.headers.get('x-rate-limit-retry-after-seconds') or 60)
            except (TypeError, ValueError):
                retry_after = 60
            if waited + retry_after > MONO_CORP_MAX_RATE_WAIT:
                raise UserError(_(
                    "monobank API rate limit exceeded. Retry in %s seconds."
                ) % retry_after)
            _logger.info("monobank corporate: rate limited, retrying in %ss", retry_after)
            sleep(retry_after)
            waited += retry_after

        if response.status_code != 200:
            try:
                error = response.json()
                message = error.get('errorDescription') or error.get('errorCode')
            except (ValueError, AttributeError):
                message = None
            raise UserError(_("monobank API error: %s") % (message or response.text))

        return response.json()

    def _mono_corp_iban(self):
        """IBAN of the account to read: set explicitly, or the journal's."""
        self.ensure_one()
        iban = _clean_iban(self.mono_account_id)
        if iban and not IBAN_UA_RE.match(iban):
            # An account ID of the personal API, left over from before the
            # switch, is not an IBAN; sending it would only return a 404.
            raise UserError(_(
                "%s is not an IBAN. The corporate API reads accounts by IBAN: "
                "enter it, or clear the field to use the journal's account."
            ) % self.mono_account_id)
        iban = iban or self._mono_journal_iban()
        if not iban:
            raise UserError(_(
                "Set the account IBAN or a bank account on the journal to read "
                "the monobank corporate statement."))
        return iban

    def _mono_corp_fetch_statement(self, date_from, date_to):
        """Read every operation booked in the period.

        The bank selects operations by the time they were *created*, while an
        operation belongs to the statement of the day it was *booked*
        (`completedTime`). The manual sync starts each period the day after
        the previous one ended, so an operation created on the last day of a
        period and booked the next day would be in neither: pending when the
        first period was read, and before the start of the second. The same
        goes for anything booked on the day of a sync after it ran. The query
        therefore reaches `MONO_CORP_LOOKBACK_DAYS` back, and
        `_mono_corp_parse` keeps everything booked up to the period end: what
        an earlier sync already imported is dropped by the id deduplication
        of the import, so only the missed operations come through.

        The bank's day is the Kyiv one, whatever the server's timezone is.
        """
        iban = self._mono_corp_iban()
        from_ts, to_ts = _kyiv_bounds(date_from, date_to)
        query_from = _kyiv_bounds(
            date_from - timedelta(days=MONO_CORP_LOOKBACK_DAYS), date_to)[0]

        items, seen = [], set()
        # One request may not span more than the bank's 31 days; the
        # look-back can push a full-length period past that.
        window_start = query_from
        while window_start <= to_ts:
            window_end = min(window_start + MONO_CORP_WINDOW_DAYS * 86400 - 1, to_ts)
            self._mono_corp_read_window(iban, window_start, window_end, items, seen)
            window_start = window_end + 1

        return {
            'api_type': 'corp_statement',
            'account_id': iban,
            'from_ts': from_ts,
            'to_ts': to_ts,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'response': items,
            'balances': self._mono_corp_fetch_balances(iban, date_from, date_to),
        }

    def _mono_corp_fetch_balances(self, iban, date_from, date_to):
        """End-of-day balances from the day before the period to its end.

        Optional: without them the statement is imported all the same, with
        derived balances that are not marked verified.
        """
        try:
            balances = self._mono_corp_request(
                f"/ext/v1/accounts/{iban}/balances",
                params={
                    'dateFrom': (date_from - timedelta(days=1)).isoformat(),
                    'dateTo': date_to.isoformat(),
                })
        except UserError as e:
            _logger.warning("monobank corporate: no balances for %s: %s", iban, e)
            return None
        return balances if isinstance(balances, list) else None

    def _mono_corp_read_window(self, iban, low, high, items, seen):
        """Append the operations created in [low, high], page by page.

        A page holds at most 500 operations, ordered by time. The next page
        continues past the last operation received, from whichever end of the
        window the page started; the ones sharing its second come again and
        are dropped by id.
        """
        for _page in range(MONO_CORP_MAX_PAGES):
            page = self._mono_corp_request(
                f"/ext/v1/statement/{iban}/{low}/{high}",
                params={'limit': MONO_CORP_PAGE_SIZE})
            if not isinstance(page, list):
                raise UserError(_("monobank API error: %s") % page)
            new = [item for item in page if item.get('id') not in seen]
            for item in new:
                seen.add(item.get('id'))
                items.append(item)
            if len(page) < MONO_CORP_PAGE_SIZE:
                return
            if not new:
                # A full page all within one second: moving the bound cannot
                # get past it, and stopping here would lose the rest quietly.
                raise UserError(_(
                    "monobank statement for %s has more than %s operations "
                    "within one second and cannot be read page by page."
                ) % (iban, MONO_CORP_PAGE_SIZE))
            first, last = page[0].get('time') or 0, page[-1].get('time') or 0
            if first <= last:
                low = last
            else:
                high = last
        raise UserError(_(
            "monobank statement for %s has more than %s pages; shorten the "
            "period.") % (iban, MONO_CORP_MAX_PAGES))

    @staticmethod
    def _mono_corp_booked_items(raw_data):
        """(booking time, item) of the DONE operations booked up to the
        period end.

        PENDING is not booked yet and DECLINED never will be. A pending
        operation is picked up by a later sync once it is DONE: the query
        reaches back past the period start, and lines are deduplicated by id.
        Booked after the period, it belongs to a later statement. There is no
        lower bound on purpose: an operation booked before the period start
        was either imported already (and is dropped as a duplicate by its id)
        or missed by the sync of that day, and then the look-back is its only
        way in.
        """
        to_ts = raw_data.get('to_ts')
        for item in raw_data.get('response') or []:
            if item.get('status', 'DONE') != 'DONE':
                continue
            booked = item.get('completedTime') or item.get('time')
            if booked and to_ts and booked > to_ts:
                continue
            yield booked, item

    def _mono_corp_parse(self, raw_data):
        """Corporate statement items into the bank_sync transaction dicts."""
        transactions = []
        for booked, item in self._mono_corp_booked_items(raw_data):
            description = item.get('description', '')
            if item.get('reverse'):
                description = _("Reversal: %s", description)
            transactions.append({
                'id': item.get('id', ''),
                'date': _kyiv_date(booked),
                # Signed kopecks: positive is incoming, negative outgoing.
                'amount': (item.get('amount') or 0) / 100.0,
                'description': description,
                'partner_name': item.get('counterName', ''),
                'partner_iban': item.get('counterIban', ''),
                'partner_edrpou': item.get('counterEdrpou', ''),
                'receipt_id': item.get('receiptId', ''),
                'external_reference': item.get('externalReference', ''),
            })
        return transactions

    def _mono_corp_balances(self, raw_data):
        """(opening, closing) from the end-of-day balances.

        Opening is the balance at the end of the day before the period,
        closing the one at the end of its last day. Either one not final
        (`isFinal = false`: the day may still change) leaves the statement
        unverified. Operations booked before the period that the look-back
        brought in are part of the opening balance already; they are taken
        out of it so that opening plus the lines gives the closing balance.
        """
        balances = raw_data.get('balances')
        if not balances or not raw_data.get('date_from'):
            return (None, None)
        by_date = {b.get('date'): b for b in balances if isinstance(b, dict)}
        date_from = date.fromisoformat(raw_data['date_from'])
        opening = by_date.get((date_from - timedelta(days=1)).isoformat())
        closing = by_date.get(raw_data.get('date_to'))
        if not (opening and closing and opening.get('isFinal')
                and closing.get('isFinal')):
            return (None, None)
        from_ts = raw_data.get('from_ts') or 0
        early = sum(
            item.get('amount') or 0
            for booked, item in self._mono_corp_booked_items(raw_data)
            if booked and booked < from_ts)
        return (round(float(opening.get('balance') or 0) - early / 100.0, 2),
                round(float(closing.get('balance') or 0), 2))

    def _mono_corp_currency_name(self, code):
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('iso_numeric', '=', int(code or 0))], limit=1)
        return currency.name or str(code)

    def _mono_corp_accounts(self):
        accounts = self._mono_corp_request('/ext/v1/accounts')
        if not isinstance(accounts, list):
            raise UserError(_("monobank API error: %s") % accounts)
        return accounts

    def _mono_corp_test_connection(self):
        accounts = self._mono_corp_accounts()
        ibans = [acc.get('iban') for acc in accounts]
        own = self._mono_corp_iban()
        if own and own not in ibans:
            message = _(
                "Connected to monobank corporate API, but account %(iban)s is "
                "not among the company's %(count)d accounts.",
                iban=own, count=len(accounts))
            kind = 'warning'
        else:
            message = _(
                "Connected to monobank corporate API. Accounts: %d",
                len(accounts))
            kind = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success') if kind == 'success' else _('Warning'),
                'message': message,
                'type': kind,
            }
        }

    def _mono_corp_fetch_accounts(self):
        accounts = self._mono_corp_accounts()
        # Corporate balances come in currency units, not in kopecks.
        account_info = [
            f"IBAN: {acc.get('iban')} | "
            f"{self._mono_corp_currency_name(acc.get('currency'))} | "
            f"Balance: {float(acc.get('balance') or 0):.2f}"
            for acc in accounts
        ]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Available Accounts'),
                'message': '\n'.join(account_info) or _('No accounts found'),
                'type': 'info',
                'sticky': True,
            }
        }


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    l10n_ua_mono_receipt_id = fields.Char(
        string='Receipt No. (check.gov.ua)',
        help='monobank receipt number of the operation, to check it on '
             'check.gov.ua.',
    )
    l10n_ua_mono_external_ref = fields.Char(
        string='External Reference',
        index='btree_not_null',
        help='Reference of a payment prepared through the monobank corporate '
             'API, as set by the sender.',
    )
