import base64
import logging
from datetime import datetime

import httpx
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Tax Cabinet API endpoints
TAX_CABINET_BASE_URL = "https://cabinet.tax.gov.ua"
TAX_CABINET_TEST_URL = "https://cabinet.tax.gov.ua:9443"  # Test environment (not fiscal)
TAX_CABINET_API_PATH = "/ws/public_api"

# DPS Server certificates for encryption
# Updated August 2025, see: https://tax.gov.ua/media-tsentr/novini/920738.html
# Старий шлях /cabinet/resources/js/sign/data/ дає 404. Крипто-дані кабінету
# тепер під /ws/api/crypto/public_sign/data/ (звідти login-сторінка тягне
# CACertificates.p7b / CAs.json). Точне ім'я cert шифрування уточнюється
# живою перевіркою; завантаження некритичне (порожній cert → підпис без
# конверта), тож помилковий URL не блокує підпис.
DPS_ENCRYPT_CERT_URL = "https://cabinet.tax.gov.ua/ws/api/crypto/public_sign/data/EK_C_NEW.cer"
DPS_SIGN_CERT_URL = "https://cabinet.tax.gov.ua/ws/api/crypto/public_sign/data/EK_S_NEW.cer"


class L10nUaTaxCabinetConfig(models.Model):
    """Підключення до електронного кабінету ДПС.

    Ключ КЕП і пароль на сервері не зберігаються й сюди не передаються (#324).
    Авторизація публічного API кабінету — КЕП-підпис коду платника в заголовку
    Authorization; його, як і підписи документів, рахує браузер
    (l10n_ua_sign), а сервер лише пересилає запити з готовим підписом.
    """
    _name = 'l10n_ua.tax.cabinet.config'
    _description = 'Tax Cabinet Configuration'
    _inherit = ['mail.thread', 'l10n_ua.sign.mixin']

    name = fields.Char(
        string='Name',
        required=True,
        default='Tax Cabinet Connection',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    taxpayer_code = fields.Char(
        string='Taxpayer Code',
        required=True,
        help='EDRPOU (for companies) or RNOKPP (for FOP)',
    )
    active = fields.Boolean(
        default=True,
    )

    # Sync settings
    last_sync_date = fields.Datetime(
        string='Last Sync',
        readonly=True,
    )
    auto_download_pdf = fields.Boolean(
        string='Auto Download PDF',
        default=True,
        help='Automatically download PDF version of documents',
    )
    auto_download_xml = fields.Boolean(
        string='Auto Download XML',
        default=True,
        help='Automatically download XML version of documents',
    )

    # Environment settings
    use_test_environment = fields.Boolean(
        string='Use Test Environment',
        default=False,
        help='Use test API (cabinet.tax.gov.ua:9443). '
             'Documents submitted to test environment are NOT fiscal - '
             'they do not go to the real tax office. '
             'Use this for testing before real submission.',
    )

    _unique_company = models.Constraint(
        'UNIQUE(company_id)',
        'Only one configuration per company allowed!',
    )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            self.taxpayer_code = self.company_id.vat or self.company_id.company_registry

    def _get_api_url(self):
        """Get API URL based on environment setting."""
        self.ensure_one()
        base_url = TAX_CABINET_TEST_URL if self.use_test_environment else TAX_CABINET_BASE_URL
        return f"{base_url}{TAX_CABINET_API_PATH}"

    def _get_base_url(self):
        """Get base URL based on environment setting."""
        self.ensure_one()
        return TAX_CABINET_TEST_URL if self.use_test_environment else TAX_CABINET_BASE_URL

    def _auth_headers(self, auth_signature):
        """Заголовки запиту до публічного API з підписом, зробленим у браузері.

        Підпис не кешується: кожен сеанс роботи з кабінетом приносить свій.
        """
        self.ensure_one()
        if not auth_signature:
            raise UserError(_("Немає КЕП-підпису для авторизації в кабінеті ДПС."))
        if isinstance(auth_signature, bytes):
            auth_signature = auth_signature.decode('ascii')
        return {
            'Authorization': auth_signature,
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'Lang': 'uk',
        }

    def _get_dps_encrypt_certificate(self):
        """Download and cache DPS encryption certificate.

        The certificate is used to encrypt documents before submission.
        Certificate URL: https://cabinet.tax.gov.ua/cabinet/resources/js/sign/data/EK_C_NEW.cer
        """
        # Check if we have a cached certificate in the attachment
        attachment = self.env['ir.attachment'].search([
            ('name', '=', 'DPS_EK_C_NEW.cer'),
            ('res_model', '=', 'l10n_ua.tax.cabinet.config'),
            ('res_id', '=', self.id),
        ], limit=1)

        if attachment:
            return base64.b64decode(attachment.datas)

        # Download certificate
        _logger.info("Downloading DPS encryption certificate from %s", DPS_ENCRYPT_CERT_URL)
        try:
            response = requests.get(DPS_ENCRYPT_CERT_URL, timeout=30)
            if response.status_code == 200:
                cert_data = response.content

                # Cache as attachment
                self.env['ir.attachment'].create({
                    'name': 'DPS_EK_C_NEW.cer',
                    'type': 'binary',
                    'datas': base64.b64encode(cert_data).decode(),
                    'res_model': 'l10n_ua.tax.cabinet.config',
                    'res_id': self.id,
                })

                return cert_data
            else:
                raise UserError(_("Failed to download DPS certificate: HTTP %s") % response.status_code)
        except requests.RequestException as e:
            raise UserError(_("Failed to download DPS certificate: %s") % str(e))

    # ========== Перевірка з'єднання (l10n_ua.sign.mixin) ==========

    def action_test_connection(self):
        """Перевірити з'єднання: браузер підписує код платника, сервер питає картку."""
        return self.action_kep_sign(mode='test')

    def kep_prepare_signing(self):
        self.ensure_one()
        if not self.taxpayer_code:
            raise UserError(_("Вкажіть код платника (ЄДРПОУ / РНОКПП)."))
        return {
            'auth_subject': self.taxpayer_code,
            'submit_label': _("Перевірити з'єднання"),
            'documents': [],
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        name = self._api_get_payer_name(auth_signature)
        return {'receipt': _("З'єднання успішне. Платник: %s") % name}

    # ========== API ==========

    def _api_get_payer_name(self, auth_signature):
        """Назва платника з картки (GET /payer_card) — перевірка авторизації."""
        self.ensure_one()
        url = f"{self._get_api_url()}/payer_card"
        headers = self._auth_headers(auth_signature)

        env_name = "TEST" if self.use_test_environment else "PRODUCTION"
        _logger.info("Tax Cabinet API [%s]: Testing connection to %s", env_name, url)
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise UserError(_("Connection failed: %s") % str(e))

        if response.status_code != 200:
            raise UserError(_("API error %s: %s") % (response.status_code, response.text))

        for item in response.json():
            if item.get('values', {}).get('FULL_NAME'):
                return item['values']['FULL_NAME']
        return "Unknown"

    def _api_get_document_list(self, year, month, *, auth_signature):
        """
        Get list of reported documents for period.

        GET /ws/public_api/reg_doc/list?periodYear=YYYY&periodMonth=MM
        """
        self.ensure_one()
        api_url = self._get_api_url()
        url = f"{api_url}/reg_doc/list"
        params = {
            'periodYear': year,
            'periodMonth': month,
        }
        headers = self._auth_headers(auth_signature)

        _logger.info("Tax Cabinet API: GET %s params=%s", url, params)
        response = requests.get(url, params=params, headers=headers, timeout=30)

        if response.status_code != 200:
            raise UserError(_("API error %s: %s") % (response.status_code, response.text))

        return response.json()

    def _api_get_incoming_documents(self, page=1, *, auth_signature):
        """
        Get incoming correspondence.

        GET /ws/public_api/post/incoming?page=N
        """
        self.ensure_one()
        api_url = self._get_api_url()
        url = f"{api_url}/post/incoming"
        params = {'page': page}
        headers = self._auth_headers(auth_signature)

        _logger.info("Tax Cabinet API: GET %s params=%s", url, params)
        response = requests.get(url, params=params, headers=headers, timeout=30)

        if response.status_code != 200:
            raise UserError(_("API error %s: %s") % (response.status_code, response.text))

        return response.json()

    def _api_get_sent_documents(self, page=1, *, auth_signature):
        """
        Get outgoing correspondence.

        GET /ws/public_api/post/sent?page=N
        """
        self.ensure_one()
        api_url = self._get_api_url()
        url = f"{api_url}/post/sent"
        params = {'page': page}
        headers = self._auth_headers(auth_signature)

        _logger.info("Tax Cabinet API: GET %s params=%s", url, params)
        response = requests.get(url, params=params, headers=headers, timeout=30)

        if response.status_code != 200:
            raise UserError(_("API error %s: %s") % (response.status_code, response.text))

        return response.json()

    def _api_download_document_pdf(self, year, doc_id, doc_type='reg_doc', *, auth_signature):
        """
        Download document PDF.

        GET /ws/public_api/reg_doc/doc/{year}/{id}/pdf
        GET /ws/public_api/post/incoming/{year}/{id}/pdf
        GET /ws/public_api/post/sent/{year}/{id}/pdf
        """
        self.ensure_one()
        api_url = self._get_api_url()

        if doc_type == 'reg_doc':
            url = f"{api_url}/reg_doc/doc/{year}/{doc_id}/pdf"
        elif doc_type == 'incoming':
            url = f"{api_url}/post/incoming/{year}/{doc_id}/pdf"
        elif doc_type == 'sent':
            url = f"{api_url}/post/sent/{year}/{doc_id}/pdf"
        else:
            raise ValueError(f"Unknown doc_type: {doc_type}")

        headers = self._auth_headers(auth_signature)

        _logger.info("Tax Cabinet API: GET %s", url)
        response = requests.get(url, headers=headers, timeout=60)

        if response.status_code != 200:
            _logger.warning("Failed to download PDF: %s", response.status_code)
            return None

        return base64.b64encode(response.content).decode()

    def _api_download_document_xml(self, year, doc_id, doc_type='reg_doc', *, auth_signature):
        """
        Download document XML.

        GET /ws/public_api/reg_doc/doc/{year}/{id}/xml
        GET /ws/public_api/post/incoming/{year}/{id}/xml
        """
        self.ensure_one()
        api_url = self._get_api_url()

        if doc_type == 'reg_doc':
            url = f"{api_url}/reg_doc/doc/{year}/{doc_id}/xml"
        elif doc_type == 'incoming':
            url = f"{api_url}/post/incoming/{year}/{doc_id}/xml"
        else:
            raise ValueError(f"Unknown doc_type for XML: {doc_type}")

        headers = self._auth_headers(auth_signature)

        _logger.info("Tax Cabinet API: GET %s", url)
        response = requests.get(url, headers=headers, timeout=60)

        if response.status_code != 200:
            _logger.warning("Failed to download XML: %s", response.status_code)
            return None

        return base64.b64encode(response.content).decode()

    def _api_submit_document_presigned(self, signed_content, filename, auth_signature):
        """Релей уже підписаного документа (клієнтське КЕП-підписування, #146).

        Ключ і пароль лишаються в браузері: сюди приходять готові
        ``signed_content`` (base64 sign+encrypt конверта на сертифікат ДПС) і
        ``auth_signature`` (base64 підпис taxpayer_code для заголовка
        Authorization). Сервер лише пересилає.
        """
        self.ensure_one()
        auth_header = auth_signature if isinstance(auth_signature, str) \
            else auth_signature.decode('utf-8')
        headers = {
            'Authorization': auth_header,
            'Accept': 'application/json, */*',
            'Lang': 'uk',
        }
        return self._post_report(signed_content, filename, headers)

    def _post_report(self, signed_content, filename, headers):
        """Спільний HTTP-релей подачі звіту в кабінет ДПС.

        Приймає готові ``headers`` (з Authorization, підписаним у браузері).
        POST на exchange/report завжди у продакшн.
        """
        self.ensure_one()

        # IMPORTANT: Test environment (port 9443) only supports PRRO operations.
        # Report submission must use production endpoint.
        base_url = TAX_CABINET_BASE_URL

        url = f"{base_url}/cabinet/public/api/exchange/report"
        # Don't set Content-Type explicitly - let requests library handle it
        # when using json= parameter (it will set application/json automatically)
        headers = dict(headers)
        headers.pop('Content-Type', None)
        headers['Accept'] = 'application/json, */*'

        # Prepare JSON payload with list array as per API spec
        content_b64 = signed_content if isinstance(signed_content, str) else signed_content.decode('utf-8')
        payload = {
            'list': [
                {
                    'contentBase64': content_b64,
                    'fname': filename,
                }
            ]
        }

        _logger.info("Tax Cabinet API [PRODUCTION]: POST %s", url)
        _logger.info("Payload filename: %s, content length: %d chars", filename, len(content_b64))

        # Remove Content-Type - let requests set it properly for json=
        submit_headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}

        try:
            # According to docs: POST /cabinet/public/api/exchange/report
            # Body: {"list": [{"contentBase64": "...", "fname": "..."}]}
            # Content-Type: application/json

            _logger.info("Request headers (without Content-Type): %s",
                        {k: (v[:50] + '...' if len(str(v)) > 50 else v)
                         for k, v in submit_headers.items()})

            response = requests.post(
                url,
                json=payload,
                headers=submit_headers,
                timeout=120,
            )

            _logger.info("Response status: %s", response.status_code)
            _logger.info("Response headers: %s", dict(response.headers))
            _logger.info("Response body (first 500 chars): %s", response.text[:500] if response.text else "empty")

        except requests.RequestException as e:
            _logger.error("Request failed: %s", str(e))
            raise UserError(_("Connection failed: %s") % str(e))

        if response.status_code in (200, 201, 202):
            _logger.info("Document submitted successfully")
            try:
                result = response.json()
            except Exception:
                result = {'message': response.text}
            return result
        else:
            error_msg = response.text
            try:
                error_data = response.json()
                error_msg = error_data.get('message', error_data.get('error', str(error_data)))
            except Exception:
                pass
            raise UserError(_("Submission failed (%s): %s") % (response.status_code, error_msg))

    def action_open_sync_wizard(self):
        """Open sync wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync with Tax Cabinet'),
            'res_model': 'l10n_ua.tax.cabinet.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_config_id': self.id,
                'default_mode': 'sync',
            },
        }
