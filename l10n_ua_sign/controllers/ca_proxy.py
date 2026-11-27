"""HTTP-проксі до ЦСК для браузерної бібліотеки підпису IIT (EndUser).

Бібліотека в режимі JS не може звертатися до серверів ЦСК (CMP, OCSP, TSP)
напряму через CORS і шле запити сюди:

    POST /l10n_ua_sign/ca_proxy?address=<хост[:порт]/шлях>&contentType=<тип>
    Content-Type: X-user/base64-data

    <base64 тіла запиту>

а у відповідь чекає base64 тіла відповіді ЦСК. Ключ і пароль сюди не
потрапляють: через проксі йдуть лише запити сертифікатів і статусів.

Щоб маршрут не став відкритим проксі (SSRF), адреса пропускається лише до
хостів ЦСК, лише http/https, без редиректів і з обмеженням розміру. Перелік
хостів: адреси з data/CAs.json, адреси з сертифікатів data/CACertificates.p7b
(OCSP, CRL, caIssuers — під час підпису бібліотека перевіряє статус сертифіката
самого КНЕДП у кореневому органі за адресою з його сертифіката) і кореневі
органи ЦЗО та ЗЦ НБУ.
"""
import base64
import binascii
import functools
import json
import logging
import os
import re
from urllib.parse import urlsplit

import requests

from odoo import http
from odoo.http import request, Response
from odoo.tools import file_path

_logger = logging.getLogger(__name__)

CAS_JSON = 'l10n_ua_sign/static/src/lib/euscp/data/CAs.json'
CA_CERTS_P7B = 'l10n_ua_sign/static/src/lib/euscp/data/CACertificates.p7b'
# Кореневі органи: Центральний засвідчувальний орган і засвідчувальний центр НБУ.
ROOT_CA_HOSTS = frozenset({'czo.gov.ua', 'zc.bank.gov.ua'})
_URL_IN_DER = re.compile(rb'https?://[\x21-\x7e]{3,256}')
_HOSTNAME = re.compile(r'[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}')
CA_ADDRESS_KEYS = ('address', 'cmpAddress', 'tspAddress', 'ocspAccessPointAddress')
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
# (з'єднання, читання). У режимі «визначати автоматично» бібліотека питає ЦСК
# по черзі, і один недоступний ЦСК із таймаутом 30 с затримував зчитування
# ключа на пів хвилини; живі ЦСК з'єднуються за мілісекунди.
TIMEOUT = (5, 20)


def _split_address(address):
    """Хост і повний URL з адреси бібліотеки: 'ca.tax.gov.ua/services/ocsp/'.

    Порожній хост означає, що адреса непридатна (інша схема, логін у URL).
    """
    address = (address or '').strip()
    if not address:
        return '', ''
    url = address if '://' in address else f'http://{address}'
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 — кидає ValueError на некоректний порт
    except ValueError:
        return '', ''
    if parts.scheme not in ('http', 'https') or parts.username or parts.password:
        return '', ''
    return (parts.hostname or '').lower(), url


@functools.lru_cache(maxsize=4)
def _hosts_from_file(path, mtime):
    with open(path, encoding='utf-8-sig') as f:
        cas = json.load(f)
    return frozenset(
        host
        for ca in cas
        for key in CA_ADDRESS_KEYS
        for host in [_split_address(ca.get(key))[0]]
        if host
    )


@functools.lru_cache(maxsize=4)
def _hosts_from_certificates(path, mtime):
    """Хости з URL у сертифікатах ЦСК (розширення AIA і CRLDP — це ASCII-рядки в DER).

    Розбирати DER повністю не треба: досить знайти http(s)-адреси й лишити ті, чий
    хост — коректне доменне ім'я (хвіст сусіднього поля DER відкидається).
    """
    with open(path, 'rb') as f:
        data = f.read()
    hosts = set()
    for raw in _URL_IN_DER.findall(data):
        host, _url = _split_address(raw.decode('ascii', 'ignore'))
        if host and _HOSTNAME.fullmatch(host):
            hosts.add(host)
    return frozenset(hosts)


def _cached_hosts(resource, reader):
    try:
        path = file_path(resource)
    except FileNotFoundError:
        return frozenset()
    return reader(path, os.path.getmtime(path))


def _allowed_hosts():
    """Хости ЦСК і кореневих органів; файли перечитуються, коли їх оновили."""
    return (ROOT_CA_HOSTS | _cached_hosts(CAS_JSON, _hosts_from_file)
            | _cached_hosts(CA_CERTS_P7B, _hosts_from_certificates))


class KepCaProxy(http.Controller):

    @http.route('/l10n_ua_sign/ca_proxy', type='http', auth='user',
                methods=['GET', 'POST'], csrf=False)
    def ca_proxy(self, address='', contentType='', **kwargs):
        host, url = _split_address(address)
        if not host or host not in _allowed_hosts():
            _logger.warning("КЕП-проксі: відхилено адресу %r", address)
            return Response('Address not allowed', status=403)

        method = request.httprequest.method
        body = None
        if method == 'POST':
            raw = request.httprequest.get_data(cache=False)
            try:
                body = base64.b64decode(raw)
            except (binascii.Error, ValueError):
                return Response('Bad request body', status=400)
            if len(body) > MAX_REQUEST_BYTES:
                return Response('Request too large', status=413)

        headers = {'Content-Type': contentType} if contentType else {}
        try:
            upstream = requests.request(
                method, url, data=body, headers=headers, timeout=TIMEOUT,
                allow_redirects=False, stream=True)
            content = upstream.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
        except requests.RequestException as e:
            _logger.warning("КЕП-проксі: ЦСК %s недоступний: %s", host, e)
            return Response('CA unavailable', status=502)

        if upstream.status_code != 200 or len(content) > MAX_RESPONSE_BYTES:
            _logger.warning("КЕП-проксі: ЦСК %s відповів %s", host, upstream.status_code)
            return Response('CA error', status=502)
        return Response(base64.b64encode(content), status=200,
                        content_type='X-user/base64-data')
