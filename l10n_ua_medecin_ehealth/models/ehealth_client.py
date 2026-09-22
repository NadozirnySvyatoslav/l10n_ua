"""HTTP client for eHealth Central Component.

Realistic skeleton — handles config, OAuth2, request logging. Real eHealth
endpoints/payload schemas are documented behind МОЗ login — adjust the
`_post_declaration()` payload structure to match your contract.
"""
import json
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class EhealthClient(models.AbstractModel):
    _name = 'l10n_ua.ehealth.client'
    _description = 'eHealth API клієнт'

    def _get_config(self):
        """Read eHealth API credentials from ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'base_url': ICP.get_str('l10n_ua_medecin_ehealth.base_url', '').rstrip('/'),
            'client_id': ICP.get_str('l10n_ua_medecin_ehealth.client_id', ''),
            'client_secret': ICP.get_str('l10n_ua_medecin_ehealth.client_secret', ''),
            'dry_run': ICP.get_str('l10n_ua_medecin_ehealth.dry_run', 'True') == 'True',
            'access_token': ICP.get_str('l10n_ua_medecin_ehealth.access_token', ''),
        }

    def _check_requests(self):
        if requests is None:
            raise UserError(_(
                'Бібліотека `requests` недоступна. Установіть через '
                '`pip install requests` у Odoo venv.'))

    def _authenticate(self):
        """OAuth2 client_credentials flow. Returns access_token string."""
        cfg = self._get_config()
        if cfg['dry_run']:
            return 'DRY-RUN-TOKEN'
        self._check_requests()
        if not (cfg['base_url'] and cfg['client_id'] and cfg['client_secret']):
            raise UserError(_('eHealth API не сконфігуровано. Налаштування → eHealth.'))
        try:
            resp = requests.post(
                f"{cfg['base_url']}/oauth/token",
                data={
                    'grant_type': 'client_credentials',
                    'client_id': cfg['client_id'],
                    'client_secret': cfg['client_secret'],
                },
                timeout=30,
            )
        except Exception as e:
            raise UserError(_('Помилка з\'єднання з eHealth: %s', str(e)))
        if resp.status_code != 200:
            raise UserError(_(
                'Не вдалося отримати токен (HTTP %(c)s): %(t)s',
                c=resp.status_code, t=resp.text[:200]))
        token = (resp.json() or {}).get('access_token')
        if not token:
            raise UserError(_('У відповіді не знайдено access_token.'))
        self.env['ir.config_parameter'].sudo().set_str(
            'l10n_ua_medecin_ehealth.access_token', token)
        return token

    def _request(self, method, path, payload=None, *, operation='unknown',
                  reference=None):
        """Generic request with logging.

        Returns (status_code, response_body_dict).
        У dry-run пише в лог і повертає (200, {'dry_run': True}).
        """
        cfg = self._get_config()
        Log = self.env['l10n_ua.ehealth.request.log'].sudo()
        if cfg['dry_run']:
            Log.create({
                'operation': operation,
                'method': method,
                'url': f"{cfg['base_url']}{path}",
                'request_body': json.dumps(payload or {}, ensure_ascii=False, indent=2),
                'response_status': 200,
                'response_body': '{"dry_run": true}',
                'reference': reference or '',
            })
            return 200, {'dry_run': True}

        self._check_requests()
        token = cfg.get('access_token') or self._authenticate()
        headers = {
            'Authorization': f"Bearer {token}",
            'Content-Type': 'application/json',
        }
        url = f"{cfg['base_url']}{path}"
        try:
            resp = requests.request(method, url, json=payload, headers=headers, timeout=60)
        except Exception as e:
            Log.create({
                'operation': operation, 'method': method, 'url': url,
                'request_body': json.dumps(payload or {}, ensure_ascii=False, indent=2),
                'response_status': 0,
                'response_body': f"Connection error: {e}",
                'reference': reference or '',
            })
            raise UserError(_('Помилка з\'єднання: %s', str(e)))
        try:
            body = resp.json()
        except Exception:
            body = {'raw': resp.text[:1000]}
        Log.create({
            'operation': operation, 'method': method, 'url': url,
            'request_body': json.dumps(payload or {}, ensure_ascii=False, indent=2),
            'response_status': resp.status_code,
            'response_body': json.dumps(body, ensure_ascii=False, indent=2)[:8000],
            'reference': reference or '',
        })
        return resp.status_code, body

    # === Domain operations ===

    def post_declaration(self, declaration):
        """Register a declaration in eHealth. Returns the UUID assigned by eHealth.

        Payload structure based on eHealth API v2 spec (declaration creation).
        Adjust as needed for your version of the API.
        """
        payload = {
            'patient': {
                'first_name': declaration.patient_id.partner_id.name.split(' ')[0] if declaration.patient_id.partner_id.name else '',
                'last_name': ' '.join(declaration.patient_id.partner_id.name.split(' ')[1:]) if declaration.patient_id.partner_id.name else '',
                'birth_date': str(declaration.patient_id.birthdate) if declaration.patient_id.birthdate else None,
                'tax_id': declaration.patient_id.rnokpp or None,
            },
            'employee_id': declaration.doctor_id.id,
            'division_id': declaration.company_id.l10n_ua_medecin_ehealth_id or None,
            'start_date': str(declaration.date_start) if declaration.date_start else None,
            'declaration_number': declaration.name,
        }
        status, body = self._request(
            'POST', '/api/declarations',
            payload=payload,
            operation='declaration_create',
            reference=declaration.name,
        )
        if status not in (200, 201):
            raise UserError(_(
                'eHealth відхилив декларацію (HTTP %(s)s): %(b)s',
                s=status, b=str(body)[:300]))
        # In dry-run we generate a fake UUID for traceability
        uuid = body.get('data', {}).get('id') if isinstance(body, dict) else None
        if not uuid and body.get('dry_run'):
            import uuid as uuid_mod
            uuid = f"dry-run-{uuid_mod.uuid4()}"
        return uuid
