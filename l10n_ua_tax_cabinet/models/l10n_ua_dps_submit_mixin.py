import base64
import json
import logging
import re

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# Статуси обробки звіту кабінетом (ReturnReport.status, API Електронного кабінету).
DPS_STATUS_MEANINGS = {
    'ERROR': 'помилка обробки',
    'ERROR_DECRYPT': 'не вдалося розшифрувати пакет',
    'ERROR_STRUCT_REPORT': 'помилка структури звіту',
    'ERROR_LINKED_DOCS': 'помилка пов\'язаних документів',
    'ERROR_DB': 'помилка бази даних ДПС',
    'ERROR_SERTIF_ORG': 'сертифікат не належить платнику',
    'ERROR_SERTIF': 'помилка сертифіката',
    'ERROR_XSD': 'XML не відповідає схемі',
    'NOT_KVT': 'квитанцію не сформовано',
}


def dps_standard_filename(xml_bytes):
    """Ім'я файлу звіту за наказом № 729: реквізити DECLARHEAD, без роздільників.

    C_REG C_RAJ TIN(10) C_DOC C_DOC_SUB C_DOC_VER(2) C_DOC_STAN C_DOC_TYPE(2)
    C_DOC_CNT(7) PERIOD_TYPE PERIOD_MONTH(2) PERIOD_YEAR C_STI_ORIG .xml
    """
    head = re.search(rb'<DECLARHEAD>(.*?)</DECLARHEAD>', xml_bytes or b'', re.S)
    if not head:
        return None
    fields = {k.decode(): v.decode('ascii', 'ignore').strip()
              for k, v in re.findall(rb'<([A-Z_]+)>([^<]*)</\1>', head.group(1))}
    try:
        return '%s%s%s%s%s%s%s%s%s%s%s%s%s.xml' % (
            fields['C_REG'].zfill(2), fields['C_RAJ'].zfill(2), fields['TIN'].zfill(10),
            fields['C_DOC'], fields['C_DOC_SUB'], fields['C_DOC_VER'].zfill(2),
            fields['C_DOC_STAN'], fields['C_DOC_TYPE'].zfill(2), fields['C_DOC_CNT'].zfill(7),
            fields['PERIOD_TYPE'], fields['PERIOD_MONTH'].zfill(2), fields['PERIOD_YEAR'],
            fields['C_STI_ORIG'].zfill(4))
    except KeyError:
        return None


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
        """Ім'я файлу звіту за стандартом ДПС (наказ № 729), якщо XML має заголовок."""
        xml = getattr(self, 'xml_file', False)
        # Odoo 20: BinaryValue — сирі байти в .content, без b64decode.
        name = dps_standard_filename(xml.content) if xml else None
        return name or getattr(self, 'xml_filename', False) or 'document.xml'

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
                # Транспортний контейнер ДПС (UA1_SIGN → UA1_CRYPT + CERTCRYPT).
                'format': 'dps_transport',
                'filename': self._dps_filename(),
                'taxpayer_code': config.taxpayer_code or '',
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
        self._dps_check_result(result)
        receipt = self._dps_receipt_text(result)
        self._dps_store_receipts(result)
        self._dps_on_submitted(receipt)
        return {'receipt': receipt}

    @api.model
    def _dps_receipt_text(self, result):
        """Відповідь кабінету на подання — у текст квитанції.

        Кабінет повертає масив результатів (по одному на поданий файл) або об'єкт.
        """
        items = result if isinstance(result, list) else [result]
        parts = []
        for item in items:
            if isinstance(item, dict):
                text = item.get('message') or item.get('status') or item.get('result')
                parts.append(str(text) if text else json.dumps(item, ensure_ascii=False))
            elif item not in (None, ''):
                parts.append(str(item))
        return '; '.join(parts) or _('Подано')

    @api.model
    def _dps_check_result(self, result):
        """Статус обробки ДПС: усе, крім OK, — відмова, а не подання."""
        for item in result if isinstance(result, list) else [result]:
            status = item.get('status') if isinstance(item, dict) else None
            if status and status != 'OK':
                raise UserError(_(
                    'ДПС не прийняла документ: %(status)s — %(meaning)s%(message)s',
                    status=status, meaning=DPS_STATUS_MEANINGS.get(status, _('невідома помилка')),
                    message=('. ' + item['message']) if item.get('message') else ''))

    def _dps_store_receipts(self, result):
        """Квитанції ДПС (kvt1, kvtList) — вкладеннями до документа."""
        self.ensure_one()
        files = []
        for item in result if isinstance(result, list) else [result]:
            if not isinstance(item, dict):
                continue
            if item.get('kvt1Base64'):
                files.append((item.get('kvt1Fname') or 'kvt1.xml', item['kvt1Base64']))
            for kvt in item.get('kvtList') or []:
                if isinstance(kvt, dict) and kvt.get('kvtBase64'):
                    files.append((kvt.get('kvtFname') or 'kvt.xml', kvt['kvtBase64']))
        for fname, data in files:
            self.env['ir.attachment'].create({
                'name': fname, 'datas': data,
                'res_model': self._name, 'res_id': self.id,
            })
        return len(files)
