import base64
import binascii
import hashlib
import logging
import time

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from odoo import fields, models

_logger = logging.getLogger(__name__)

MONO_PUBKEY_URL = 'https://api.monobank.ua/api/merchant/pubkey'
MONO_PUBKEY_REFRESH_SEC = 300

# Публічний ключ мерчанта в пам'яті процесу:
# sha256(токен) -> (PEM bytes, monotonic-час отримання).
_MONO_PUBKEY_CACHE = {}


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    mono_acquiring_token = fields.Char(
        string="Токен Monobank Acquiring",
        help="Токен мерчанта з кабінету Monobank (розділ Acquiring). "
             "Прив'язується до банківського журналу, куди зараховуються "
             "карткові оплати.",
    )

    # ------------------------------------------------------------------
    # Підпис webhook (X-Sign)
    # ------------------------------------------------------------------

    def _mono_cache_key(self):
        self.ensure_one()
        return hashlib.sha256((self.mono_acquiring_token or '').encode()).hexdigest()

    def _mono_fetch_pubkey(self):
        """Публічний ключ мерчанта з API Monobank (base64 від PEM)."""
        self.ensure_one()
        resp = requests.get(
            MONO_PUBKEY_URL,
            headers={'X-Token': self.mono_acquiring_token},
            timeout=10,
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()['key'])

    def _mono_get_pubkey(self, refresh=False):
        """PEM ключа з кешу. `refresh` — запитати заново, але не частіше
        ніж раз на MONO_PUBKEY_REFRESH_SEC, щоб підроблені запити не
        смикали API Monobank."""
        self.ensure_one()
        cache_key = self._mono_cache_key()
        cached = _MONO_PUBKEY_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and (not refresh
                       or now - cached[1] < MONO_PUBKEY_REFRESH_SEC):
            return None if refresh else cached[0]
        try:
            pem = self._mono_fetch_pubkey()
        except Exception:
            _logger.warning(
                "Monobank: не вдалося отримати публічний ключ для журналу %s",
                self.id, exc_info=True)
            return None
        _MONO_PUBKEY_CACHE[cache_key] = (pem, now)
        return pem

    @staticmethod
    def _mono_check_sign(pem, body, x_sign):
        """ECDSA (SHA-256) підпис тіла запиту ключем мерчанта."""
        try:
            key = serialization.load_pem_public_key(pem)
            if not isinstance(key, ec.EllipticCurvePublicKey):
                return False
            key.verify(base64.b64decode(x_sign), body, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError, TypeError, binascii.Error):
            return False

    def _mono_verify_webhook(self, body, x_sign):
        """Чи підписано `body` ключем мерчанта одного з журналів `self`.

        Ключ кешується; якщо підпис не зійшовся, ключ запитується повторно
        один раз (Monobank може змінити ключ).
        """
        if not body or not x_sign or not isinstance(x_sign, str):
            return False
        for journal in self.filtered('mono_acquiring_token'):
            for refresh in (False, True):
                pem = journal._mono_get_pubkey(refresh=refresh)
                if pem and self._mono_check_sign(pem, body, x_sign):
                    return True
        return False
