import logging
import requests
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# monobank API base URL
MONO_API_URL = "https://api.monobank.ua"


class L10nUaBankSyncConfig(models.Model):
    """Extend base config with monobank provider."""
    _inherit = 'l10n_ua.bank.sync.config'

    provider = fields.Selection(
        selection_add=[('mono', 'monobank')],
        ondelete={'mono': 'set default'},
    )

    # monobank API Credentials
    mono_api_token = fields.Char(
        string='API Token',
        help='Personal token from monobank settings (Настройки → API)',
    )
    mono_account_id = fields.Char(
        string='Account ID',
        help='monobank account ID (optional, fetched automatically)',
    )

    # Webhook
    mono_webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_mono_webhook_url',
    )
    mono_webhook_active = fields.Boolean(
        string='Webhook Active',
        default=False,
    )

    @api.depends_context('company')
    def _compute_mono_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        for record in self:
            record.mono_webhook_url = f'{base_url}/l10n_ua_bank_mono/webhook/{record.id}'

    def _fetch_from_bank(self, date_from, date_to):
        """Fetch statements from monobank API."""
        self.ensure_one()

        if self.provider != 'mono':
            return super()._fetch_from_bank(date_from, date_to)

        if not self.mono_api_token:
            raise UserError(_("Please configure monobank API Token"))

        # monobank API limits to 31 days
        days_diff = (date_to - date_from).days
        if days_diff > 31:
            raise UserError(_("monobank API allows maximum 31 days per request"))

        # Get account ID if not set
        account_id = self.mono_account_id
        if not account_id:
            account_id = self._mono_get_default_account()
            if account_id:
                self.mono_account_id = account_id

        if not account_id:
            raise UserError(_("Could not determine monobank account ID"))

        # Convert dates to timestamps
        from_ts = int(datetime.combine(date_from, datetime.min.time()).timestamp())
        to_ts = int(datetime.combine(date_to, datetime.max.time()).timestamp())

        url = f"{MONO_API_URL}/personal/statement/{account_id}/{from_ts}/{to_ts}"

        headers = {
            'X-Token': self.mono_api_token,
        }

        _logger.info("monobank: Fetching %s", url)

        response = requests.get(url, headers=headers, timeout=60)

        _logger.info("monobank: Response status %s", response.status_code)

        if response.status_code == 429:
            raise UserError(_("monobank API rate limit exceeded. Please wait 60 seconds."))

        if response.status_code != 200:
            raise UserError(_("monobank API error: %s") % response.text)

        data = response.json()

        return {
            'api_type': 'statement',
            'account_id': account_id,
            'from_ts': from_ts,
            'to_ts': to_ts,
            'response': data,
        }

    def _mono_get_default_account(self):
        """Get default (first UAH) account from client info."""
        url = f"{MONO_API_URL}/personal/client-info"
        headers = {'X-Token': self.mono_api_token}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                accounts = data.get('accounts', [])
                # Find UAH account (currency code 980)
                for acc in accounts:
                    if acc.get('currencyCode') == 980:
                        return acc.get('id')
                # Fallback to first account
                if accounts:
                    return accounts[0].get('id')
        except Exception as e:
            _logger.error("monobank: Failed to get client info: %s", str(e))

        return None

    def _parse_transactions(self, raw_data):
        """Parse monobank API response into transaction list."""
        self.ensure_one()

        if self.provider != 'mono':
            return super()._parse_transactions(raw_data)

        transactions = []
        items = raw_data.get('response', [])

        if not isinstance(items, list):
            return []

        for item in items:
            # monobank amounts are in kopeks (cents) and already signed:
            # - Positive = incoming (credit to account, Кт)
            # - Negative = outgoing (debit from account, Дт)
            amount = item.get('amount', 0) / 100.0

            # Get transaction time
            trans_time = item.get('time', 0)
            if trans_time:
                trans_date = datetime.fromtimestamp(trans_time).strftime('%Y-%m-%d')
            else:
                trans_date = ''

            trans = {
                'id': item.get('id', ''),
                'date': trans_date,
                'amount': amount,
                'description': item.get('description', ''),
                'partner_name': item.get('counterName', ''),
                'partner_iban': item.get('counterIban', ''),
                'partner_edrpou': item.get('counterEdrpou', ''),
            }
            transactions.append(trans)

        return transactions

    def action_test_connection(self):
        """Test monobank API connection."""
        self.ensure_one()

        if self.provider != 'mono':
            return super().action_test_connection()

        if not self.mono_api_token:
            raise UserError(_("Please configure API Token"))

        try:
            url = f"{MONO_API_URL}/personal/client-info"
            headers = {'X-Token': self.mono_api_token}

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                client_name = data.get('name', 'Unknown')
                accounts_count = len(data.get('accounts', []))

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Connected to monobank. Client: %s, Accounts: %d') % (client_name, accounts_count),
                        'type': 'success',
                    }
                }
            elif response.status_code == 429:
                raise UserError(_("Rate limit exceeded. Please wait 60 seconds."))
            else:
                raise UserError(_("API returned error: %s") % response.text)

        except requests.exceptions.RequestException as e:
            raise UserError(_("Connection failed: %s") % str(e))

    def action_fetch_accounts(self):
        """Fetch available accounts from monobank."""
        self.ensure_one()

        if not self.mono_api_token:
            raise UserError(_("Please configure API Token"))

        url = f"{MONO_API_URL}/personal/client-info"
        headers = {'X-Token': self.mono_api_token}

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            raise UserError(_("Failed to fetch accounts: %s") % response.text)

        data = response.json()
        accounts = data.get('accounts', [])

        # Format account list for display
        account_info = []
        for acc in accounts:
            currency = acc.get('currencyCode', 0)
            currency_name = 'UAH' if currency == 980 else str(currency)
            balance = acc.get('balance', 0) / 100.0
            account_info.append(f"ID: {acc.get('id')} | {currency_name} | Balance: {balance:.2f}")

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
