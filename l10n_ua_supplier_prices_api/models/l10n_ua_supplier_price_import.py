import base64
import json
import logging
from urllib.parse import urlparse

import requests

from odoo import models, _
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_supplier_prices_base.tools.json_path import resolve_first

_logger = logging.getLogger(__name__)


class L10nUaSupplierPriceImport(models.Model):
    _inherit = 'l10n_ua.supplier.price.import'

    def _do_fetch(self):
        self.ensure_one()
        if self.source_id.fetcher_type == 'api':
            return self._fetch_api()
        return super()._do_fetch()

    def _fetch_api(self):
        self.ensure_one()
        config = self._get_connection_config()
        url = config.get('url')
        if not url:
            raise UserError(_("API config must include 'url'."))

        timeout = self.source_id.fetch_timeout
        session = requests.Session()
        self._apply_auth(session, config)
        headers = dict(config.get('headers') or {})
        params = config.get('params') or {}
        method = (config.get('method') or 'GET').upper()
        body = config.get('body')

        try:
            response = session.request(
                method, url, params=params, headers=headers,
                json=body if body else None,
                timeout=(timeout, timeout),
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            raise UserError(_("API timeout after %(t)ss: %(e)s", t=timeout, e=e))
        except requests.exceptions.RequestException as e:
            raise UserError(_("API request failed: %s") % e)

        response_type = config.get('response_type', 'file')

        if response_type == 'json_indirect':
            try:
                data = response.json()
            except ValueError as e:
                raise UserError(_("Expected JSON response, got: %s") % e)
            file_url = resolve_first(data, config.get('json_indirect_path', ''))
            if not file_url or not isinstance(file_url, str):
                raise UserError(_(
                    "Path '%s' did not resolve to a file URL in JSON response.",
                    config.get('json_indirect_path'),
                ))
            try:
                file_resp = session.get(file_url, timeout=(timeout, timeout))
                file_resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise UserError(_("Indirect file fetch failed: %s") % e)
            content = file_resp.content
            filename = self._extract_filename(file_resp, file_url)
        else:
            content = response.content
            filename = self._extract_filename(response, url)

        self.write({
            'raw_file': base64.b64encode(content).decode(),
            'raw_filename': filename,
        })

    def _get_connection_config(self):
        """Розпарсити connection_config JSON. {} якщо порожнє."""
        raw = self.source_id.connection_config
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            raise UserError(_(
                "Invalid connection_config JSON on source '%s'",
            ) % self.source_id.name)

    def _apply_auth(self, session, config):
        auth_type = (config.get('auth_type') or 'none').lower()
        if auth_type == 'none':
            return
        if auth_type == 'basic':
            session.auth = (config.get('username', ''), config.get('password', ''))
            return
        if auth_type == 'bearer':
            token = config.get('token', '')
            session.headers['Authorization'] = f'Bearer {token}'
            return
        if auth_type == 'api_key_header':
            name = config.get('header_name') or 'X-API-Key'
            session.headers[name] = config.get('token', '')
            return
        raise UserError(_("Unknown auth_type: %s") % auth_type)

    def _extract_filename(self, response, url):
        """Витягти ім'я файлу з Content-Disposition, інакше з URL."""
        disposition = response.headers.get('Content-Disposition', '')
        if 'filename=' in disposition:
            part = disposition.split('filename=')[1].strip()
            return part.strip('"').strip("'").split(';')[0].strip()
        parsed = urlparse(url)
        name = parsed.path.rsplit('/', 1)[-1]
        return name or 'downloaded_file'
