"""HTTP client of the Вчасно.ЕДО API v2.

Paths and fields as used by working integrations of the API: documents are
uploaded as multipart ``files`` to ``/documents`` with query parameters,
listed by ``/documents?ids=…`` and ``/incoming-documents``, downloaded from
``/documents/<id>/original`` and ``/documents/<id>/archive``. Amounts are in
kopecks. Every call has a timeout and turns an HTTP error into a message the
user can act on.
"""

import logging
import re

import requests

_logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = 'https://vchasno.ua/api/v2'
TIMEOUT = 60


class VchasnoError(Exception):
    """An answer of the API that is not a success."""


class VchasnoClient:

    def __init__(self, token, base_url=DEFAULT_BASE_URL, session=None):
        self.token = token
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self.session = session or requests.Session()

    def _request(self, method, path, **kwargs):
        url = f'{self.base_url}/{path.lstrip("/")}'
        headers = dict(kwargs.pop('headers', {}), Authorization=self.token)
        try:
            response = self.session.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as error:
            raise VchasnoError(f'Вчасно недоступне: {error}') from error
        if response.status_code == 401 or response.status_code == 403:
            raise VchasnoError('Вчасно відхилило токен (HTTP %s): перевірте токен API.' % response.status_code)
        if response.status_code >= 400:
            raise VchasnoError('Вчасно повернуло помилку HTTP %s: %s'
                               % (response.status_code, (response.text or '')[:500]))
        return response

    @staticmethod
    def _documents(payload):
        """The list of documents of an answer: {'documents': […]} or […]."""
        if isinstance(payload, dict):
            return payload.get('documents') or ([payload] if payload.get('id') else [])
        return payload or []

    def categories(self):
        return self._request('GET', '/document-categories').json()

    def upload(self, filename, content, params):
        response = self._request(
            'POST', '/documents',
            files={'files': (filename, content, 'application/pdf')},
            params={k: v for k, v in params.items() if v not in (None, False, '', [])})
        documents = self._documents(response.json())
        if not documents:
            raise VchasnoError('Вчасно не повернуло завантажений документ.')
        return documents[0]

    def send(self, document_id):
        self._request('POST', f'/documents/{document_id}/send')

    def documents(self, ids):
        if not ids:
            return []
        return self._documents(self._request('GET', '/documents', params={'ids': ','.join(ids)}).json())

    def incoming(self, date_from=None):
        params = {'date_created_from': date_from.isoformat()} if date_from else {}
        return self._documents(self._request('GET', '/incoming-documents', params=params).json())

    def download(self, document_id, kind):
        response = self._request('GET', f'/documents/{document_id}/{kind}')
        disposition = response.headers.get('Content-Disposition', '')
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
        default = f'{document_id}.{"zip" if kind == "archive" else "pdf"}'
        return (match.group(1) if match else default), response.content
