import base64
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaDpsSubmitMixin(models.AbstractModel):
    """Подання документа до ДПС через клієнтський КЕП-підпис.

    Наслідує l10n_ua.sign.mixin і реалізує його контракт для типового випадку
    «підписати XML → зашифрувати на сертифікат ДПС → подати в кабінет».
    Споживачу достатньо:

    * мати поля ``company_id``, ``xml_file`` (Binary, base64 XML), ``xml_filename``;
    * перевизначити ``_dps_ensure_xml()`` (згенерувати XML, якщо його ще нема),
      ``_dps_submit_label()`` і ``_dps_on_submitted(receipt)`` (зафіксувати стан);
    * кнопку подання прив'язати до ``action_kep_submit()``.

    Специфіку ДПС (пошук конфігурації кабінету, сертифікат шифрування, реле)
    тримаємо тут, щоб декларації/накладні/запити не дублювали її.
    """
    _name = 'l10n_ua.dps.submit.mixin'
    _inherit = 'l10n_ua.sign.mixin'
    _description = 'Подання до ДПС через КЕП-підпис'

    # --- ДПС-специфіка ---

    def _dps_config(self):
        """Активна конфігурація кабінету ДПС для компанії запису (або UserError)."""
        self.ensure_one()
        company = self.company_id
        config = self.env['l10n_ua.tax.cabinet.config'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        if not config:
            raise UserError(_(
                'Не налаштовано кабінет ДПС / КЕП для компанії «%s». '
                'Створіть конфігурацію (Кабінет ДПС) перед поданням.'
            ) % company.display_name)
        return config

    def _dps_recipient_cert_b64(self, config):
        """Сертифікат шифрування ДПС (base64) — некритично: 404 не блокує підпис."""
        try:
            cert = config._get_dps_encrypt_certificate()
            return base64.b64encode(cert).decode() if cert else ''
        except Exception as e:
            _logger.warning('DPS cert недоступний (%s) — підпис без конверта.', e)
            return ''

    # --- хуки споживача (за замовчуванням працюють з xml_file/xml_filename) ---

    def _dps_ensure_xml(self):
        """Згенерувати XML, якщо його ще нема (перевизначає споживач)."""
        return

    def _dps_document_b64(self):
        self._dps_ensure_xml()
        xml = self.xml_file if 'xml_file' in self._fields else False
        if not xml:
            raise UserError(_('Немає XML для підпису — згенеруйте документ.'))
        # Odoo 20 keeps binaries raw in a BinaryValue; the browser signer
        # expects base64.
        return xml.to_base64()

    def _dps_filename(self):
        return getattr(self, 'xml_filename', False) or 'document.xml'

    def _dps_submit_label(self):
        return _('Подати до ДПС')

    def _dps_on_submitted(self, receipt):
        """Зафіксувати результат подання (перевизначає споживач)."""
        return

    def _dps_check_can_submit(self):
        """Перевірка перед підписом/поданням (напр. лише чернетки).

        Перевизначає споживач; кидає UserError, якщо подавати не можна.
        """
        return

    # --- відкриття діалогу підпису ---

    def action_kep_submit(self):
        """Перевірити XML/конфіг і відкрити універсальний діалог КЕП-підпису."""
        self.ensure_one()
        self._dps_check_can_submit()
        self._dps_ensure_xml()
        self._dps_config()
        return self.action_kep_sign()

    # --- контракт l10n_ua.sign.mixin ---

    def kep_prepare_signing(self):
        self.ensure_one()
        self._dps_check_can_submit()
        config = self._dps_config()
        return {
            'auth_subject': config.taxpayer_code or '',
            'submit_label': self._dps_submit_label(),
            'documents': [{
                'name': 'doc',
                'data_b64': self._dps_document_b64(),
                'format': 'envelope',
                'filename': self._dps_filename(),
                'recipient_cert_b64': self._dps_recipient_cert_b64(config),
            }],
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        self._dps_check_can_submit()
        config = self._dps_config()
        envelope = signed.get('doc')
        if not envelope:
            raise UserError(_('Не отримано підпис документа.'))
        result = config._api_submit_document_presigned(
            envelope, self._dps_filename(), auth_signature)
        receipt = result.get('message') if isinstance(result, dict) else str(result)
        self._dps_on_submitted(receipt)
        return {'receipt': receipt}
