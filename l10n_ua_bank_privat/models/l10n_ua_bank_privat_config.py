import base64
import logging
import re
import requests
import time
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
# Тестам: підмінити, щоб не чекати інтервалу між запитами.
sleep = time.sleep
# Час останнього запиту до API (інтервал ≤ 1 запит/с).
_privat_last_call = 0.0

# Розкладка колонок виписки Приват24 Бізнес (експорт XLS, BIFF8).
# Шапка таблиці — рядок з «№ документа» у колонці 0; дані — далі.
PRIVAT_XLS_COL_DOC = 0        # № документа
PRIVAT_XLS_COL_DATE = 1       # Дата операції (ДД.ММ.РРРР)
PRIVAT_XLS_COL_AMOUNT = 3     # Сума (знакова: − списання, + надходження)
PRIVAT_XLS_COL_PURPOSE = 5    # Призначення платежу
PRIVAT_XLS_COL_EDRPOU = 6     # ЄДРПОУ/РНОКПП контрагента
PRIVAT_XLS_COL_CNTR_NAME = 7  # Назва контрагента
PRIVAT_XLS_COL_CNTR_ACC = 8   # Рахунок контрагента
PRIVAT_XLS_COL_REF = 10       # Референс

# API «Автоклієнт» (Приват24 для бізнесу). Опис API — офіційний документ банку
# «Опис API Автоклієнт», посилання з https://privatbank.ua/business/intehratsiya
PRIVAT_ACP_URL = 'https://acp.privatbank.ua/api'
# Обов'язкові заголовки: User-Agent, token, Content-Type (charset utf8|cp1251;
# без charset банк вважає cp1251, тому зазначаємо utf-8 явно).
PRIVAT_USER_AGENT = 'Odoo l10n_ua_bank_privat'
PRIVAT_CONTENT_TYPE = 'application/json;charset=utf-8'
# Розмір пачки: за замовчуванням банк віддає 20, максимум 500, рекомендовано
# не більше 100. Решту отримуємо через followId = next_page_id.
PRIVAT_PAGE_SIZE = 100
# Запобіжник від нескінченного циклу: 1000 пачок × 100 = 100 000 записів.
PRIVAT_MAX_PAGES = 1000
# Банк рекомендує не частіше 1 запиту на секунду.
PRIVAT_REQUEST_INTERVAL = 1.0
IBAN_UA_RE = re.compile(r'^UA\d{27}$')
# Стан проведення PR_PR: r – проведена, p – проводиться, t – сторнована,
# n – забракована. У виписку йдуть лише проведені.
PRIVAT_PR_PR_BOOKED = 'r'


class L10nUaBankSyncConfig(models.Model):
    """Extend base config with PrivatBank provider (online API + XLS file)."""
    _inherit = 'l10n_ua.bank.sync.config'

    provider = fields.Selection(
        selection_add=[
            ('privat', 'PrivatBank'),
            ('privat_xls', 'PrivatBank (файл виписки)'),
        ],
        ondelete={'privat': 'set default', 'privat_xls': 'set default'},
    )

    # PrivatBank API Credentials
    privat_api_token = fields.Char(
        string='API Token',
        help='Token from Privat24 Business Autoclient',
        # Токен дає доступ до рахунків (а без обмежень сервісів — і до
        # створення платежів): бачить і змінює лише керівник; синхронізація
        # читає його через sudo().
        groups='l10n_ua_account_base.group_ua_manager',
        copy=False,
    )
    privat_account_iban = fields.Char(
        string='Account IBAN',
        help='Account IBAN (UA + 27 digits). Leave empty to use the IBAN of '
             'the bank account of the journal.',
    )
    privat_group_client_id = fields.Char(
        string='Client ID in group',
        help='Only for an Autoclient connected for a group of individual '
             'entrepreneurs (група ФОП): ID of the entrepreneur in the group, '
             'sent as the "id" parameter. Leave empty otherwise - the bank '
             'rejects the parameter outside group mode.',
    )

    # Legacy Merchant API
    privat_merchant_id = fields.Char(
        string='Merchant ID',
        help='Legacy merchant ID (for old API)',
    )
    privat_merchant_password = fields.Char(
        string='Merchant Password',
        help='Legacy merchant password (for old API)',
        groups='l10n_ua_account_base.group_ua_manager',
        copy=False,
    )
    privat_card_number = fields.Char(
        string='Card Number',
        help='Card number for statement retrieval (16 digits)',
    )

    def _source_type(self):
        if self.provider == 'privat_xls':
            return 'file'
        return super()._source_type()

    def _fetch_from_bank(self, date_from, date_to):
        """Fetch statements from PrivatBank API."""
        self.ensure_one()

        if self.provider == 'privat_xls':
            raise UserError(_(
                'PrivatBank (файл виписки) — файловий провайдер. Скористайтесь '
                'майстром «Імпорт виписки з файлу», щоб завантажити файл виписки '
                'з Приват24 Бізнес (XLS / XLSX / CSV / MultiCash-ZIP).'))

        if self.provider != 'privat':
            return super()._fetch_from_bank(date_from, date_to)

        # Токен закритий групою керівника — синхронізацію запускає й
        # бухгалтер, і cron, тож читаємо його через sudo.
        if self.sudo().privat_api_token:
            return self._privat_fetch_autoclient(date_from, date_to)
        elif self.privat_merchant_id:
            return self._privat_fetch_merchant(date_from, date_to)
        else:
            raise UserError(_("Please configure PrivatBank API Token or Merchant credentials"))

    # ------------------------------------------------------------------
    # API «Автоклієнт»
    # ------------------------------------------------------------------

    def _privat_headers(self):
        """Обов'язкові заголовки запиту. Ніколи не логувати — тут токен."""
        self.ensure_one()
        token = (self.sudo().privat_api_token or '').strip()
        if not token:
            raise UserError(_("Please configure API Token"))
        return {
            'User-Agent': PRIVAT_USER_AGENT,
            'token': token,
            'Content-Type': PRIVAT_CONTENT_TYPE,
        }

    def _privat_iban(self):
        """IBAN рахунку виписки: заданий явно або рахунок журналу.

        Без ``acc`` банк віддає дані за всіма активними рахунками разом —
        у журнал одного рахунку потрапили б чужі рухи, тому рахунок
        обов'язковий.
        """
        self.ensure_one()
        iban = (self.privat_account_iban or '').replace(' ', '').upper()
        if not iban:
            iban = (self.bank_account_id.acc_number or '').replace(' ', '').upper()
        if not iban:
            raise UserError(_(
                'Зазначте IBAN рахунку ПриватБанку (поле «Account IBAN») або '
                'банківський рахунок у журналі: без рахунку банк повертає '
                'рухи за всіма рахунками підприємства одразу.'))
        if not IBAN_UA_RE.match(iban):
            raise UserError(_(
                '«%s» — не IBAN (UA + 27 цифр). API «Автоклієнт» приймає '
                'рахунок у форматі IBAN.') % iban)
        return iban

    @staticmethod
    def _privat_error_text(response):
        """Текст помилки з тіла відповіді банку {status, code, message, …}."""
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            parts = [str(body[k]) for k in ('message', 'code', 'serviceCode')
                     if body.get(k)]
            if parts:
                return ' / '.join(parts)
        return (response.text or '').strip()[:500]

    def _privat_request(self, path, params=None):
        """GET до API «Автоклієнт» → розібраний JSON зі status = SUCCESS.

        Дотримується рекомендованого банком інтервалу (≤ 1 запит/с).
        Логуються лише шлях, параметри (без токена) і код відповіді.
        """
        self.ensure_one()
        params = dict(params or {})
        if self.privat_group_client_id:
            params['id'] = self.privat_group_client_id.strip()
        url = PRIVAT_ACP_URL + path
        headers = self._privat_headers()

        global _privat_last_call
        wait = PRIVAT_REQUEST_INTERVAL - (time.monotonic() - _privat_last_call)
        if wait > 0:
            sleep(wait)
        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
        except requests.exceptions.RequestException as e:
            # Текст винятку requests містить URL (параметри), але не заголовки.
            raise UserError(_("Connection failed: %s") % str(e))
        finally:
            _privat_last_call = time.monotonic()

        _logger.info("PrivatBank Autoclient: GET %s %s -> %s",
                     path, params, response.status_code)

        if response.status_code != 200:
            detail = self._privat_error_text(response)
            if response.status_code == 401:
                raise UserError(_(
                    'ПриватБанк відхилив токен «Автоклієнта» (HTTP 401). '
                    'Перевірте токен у налаштуваннях API в «Приват24 для '
                    'бізнесу». %s') % detail)
            if response.status_code == 403:
                raise UserError(_(
                    'Доступ заборонено (HTTP 403): застосунок API вимкнено або '
                    'для нього не дозволено сервіс «Отримання балансів і '
                    'транзакцій за рахунками». %s') % detail)
            raise UserError(_("PrivatBank API error: %s") % (
                '%s %s' % (response.status_code, detail)))

        try:
            data = response.json()
        except ValueError:
            raise UserError(_("PrivatBank API error: %s") % (
                response.text or '')[:500])
        if not isinstance(data, dict):
            raise UserError(_("PrivatBank API error: %s") % str(data)[:500])
        status = str(data.get('status') or '').upper()
        if status and status != 'SUCCESS':
            raise UserError(_("PrivatBank API error: %s") % (
                ' / '.join(str(data[k]) for k in ('message', 'code', 'serviceCode')
                           if data.get(k)) or status))
        return data

    def _privat_paged(self, path, params, key):
        """Усі пачки списку ``key`` (transactions / balances).

        Банк віддає дані пачками; поки ``exist_next_page`` істинний,
        ``next_page_id`` підставляється в ``followId`` наступного запиту.
        """
        items = []
        params = dict(params, limit=PRIVAT_PAGE_SIZE)
        follow_ids = set()
        for _page in range(PRIVAT_MAX_PAGES):
            data = self._privat_request(path, params)
            page = data.get(key) or []
            if not isinstance(page, list):
                raise UserError(_("PrivatBank API error: %s") % str(data)[:500])
            items.extend(page)
            next_id = data.get('next_page_id')
            if not data.get('exist_next_page') or not next_id:
                return items
            if next_id in follow_ids:
                raise UserError(_(
                    'ПриватБанк повторно повернув ту саму пачку (%s) — '
                    'виписка неповна, синхронізацію зупинено.') % next_id)
            follow_ids.add(next_id)
            params['followId'] = next_id
        raise UserError(_(
            'Виписка ПриватБанку має понад %s пачок по %s записів — '
            'скоротіть період.') % (PRIVAT_MAX_PAGES, PRIVAT_PAGE_SIZE))

    def _privat_settings(self):
        """Серверні дати банку; не продовжуємо, поки йде регламент."""
        settings = self._privat_request('/statements/settings').get('settings') or {}
        if str(settings.get('work_balance') or '').upper() == 'Y':
            raise UserError(_(
                'ПриватБанк виконує регламентні роботи (work_balance = Y) — '
                'банк просить у цей час запитів не робити. Повторіть '
                'синхронізацію пізніше.'))
        if settings.get('phase') and settings.get('phase') != 'WRK':
            _logger.warning("PrivatBank Autoclient: phase is %s, the bank may "
                            "answer with errors", settings.get('phase'))
        return settings

    def _privat_fetch_autoclient(self, date_from, date_to):
        """Транзакції та залишки за період з API «Автоклієнт».

        ``/statements/transactions`` і ``/statements/balance`` за інтервалом
        дат охоплюють і підсумкові дні, і поточний (проміжний) — окремі
        ``/interim`` і ``/final`` потрібні лише для «від lastday до today» та
        «останній підсумковий день». Ще не проведені рухи (PR_PR ≠ r) у
        виписку не йдуть; наступна синхронізація перекриває період і підбере
        їх, коли банк проведе (рядки дедуплікуються за REF+REFN).
        """
        self.ensure_one()
        iban = self._privat_iban()
        settings = self._privat_settings()
        params = {
            'acc': iban,
            'startDate': date_from.strftime('%d-%m-%Y'),
            'endDate': date_to.strftime('%d-%m-%Y'),
        }
        transactions = self._privat_paged(
            '/statements/transactions', params, 'transactions')
        try:
            balances = self._privat_paged('/statements/balance', params, 'balances')
        except UserError as e:
            # Без залишків виписка однаково імпортується, лише не звірена.
            _logger.warning("PrivatBank Autoclient: balances unavailable: %s", e)
            balances = None

        return {
            'api_type': 'autoclient',
            'url': PRIVAT_ACP_URL + '/statements/transactions',
            'acc': iban,
            'params': params,
            'settings': settings,
            'response': {'transactions': transactions},
            'balances': balances,
        }

    def _privat_fetch_merchant(self, date_from, date_to):
        """Fetch via legacy Merchant API."""
        _logger.info("PrivatBank: Using Merchant API")

        if not self.privat_card_number:
            raise UserError(_("Card number is required for Merchant API"))

        url = "https://api.privatbank.ua/p24api/rest_fiz"

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
        <request version="1.0">
            <merchant>
                <id>{self.privat_merchant_id}</id>
                <signature></signature>
            </merchant>
            <data>
                <oper>cmt</oper>
                <wait>0</wait>
                <test>0</test>
                <payment id="">
                    <prop name="sd" value="{date_from.strftime('%d.%m.%Y')}"/>
                    <prop name="ed" value="{date_to.strftime('%d.%m.%Y')}"/>
                    <prop name="card" value="{self.privat_card_number}"/>
                </payment>
            </data>
        </request>"""

        response = requests.post(url, data=xml_data, timeout=60)

        if response.status_code != 200:
            raise UserError(_("PrivatBank Merchant API error"))

        return {
            'api_type': 'merchant',
            'url': url,
            'response_text': response.text,
        }

    # ------------------------------------------------------------------
    # PrivatBank XLS file provider (Приват24 Бізнес → експорт XLS)
    # ------------------------------------------------------------------

    def _file_to_payload(self, content, filename=None):
        """Байти файлу виписки → JSON-безпечний payload (base64)."""
        if self.provider == 'privat_xls':
            return {'privat_xls_b64': base64.b64encode(content).decode('ascii')}
        return super()._file_to_payload(content, filename)

    def _extract_balances(self, raw_data):
        """Вхідний/вихідний залишок з файлу виписки ПриватБанку.

        Вхідний залишок = сума рядка «#ПЕРЕНЕСЕННЯ ЗАЛИШКУ»; вихідний =
        вхідний + Σ рухів. Так виписка отримує коректний balance_start, і
        показаний кінцевий баланс збігається з реальним (а не лише Σ рухів).
        """
        if self.provider == 'privat':
            if (raw_data or {}).get('api_type') == 'autoclient':
                return self._privat_autoclient_balances(raw_data)
            return (None, None)
        if self.provider != 'privat_xls':
            return super()._extract_balances(raw_data)
        transactions, opening = self._privat_file_parse(raw_data)
        if opening is None:
            return (None, None)
        closing = round(opening + sum(t['amount'] for t in transactions), 2)
        return (opening, closing)

    def action_privat_xls_open_import(self):
        """Відкрити майстер імпорту виписки XLS для цього конфігу."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Імпорт виписки з файлу'),
            'res_model': 'l10n_ua.bank.statement.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }

    @staticmethod
    def _privat_cell(value):
        """Клітинку у рядок: цілі float ('14360570.0') → '14360570'."""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @staticmethod
    def _privat_amount(value):
        """Знакова сума: приймає число або текст ('-100 000.00', '750,00')."""
        if isinstance(value, (int, float)):
            return float(value)
        text = (str(value).strip().replace(' ', '').replace('\xa0', '')
                .replace(',', '.'))
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _privat_date(raw):
        """'ДД.ММ.РРРР' → 'РРРР-ММ-ДД'; '' якщо не дата."""
        raw = (raw or '').strip()
        if not raw or '.' not in raw:
            return ''
        parts = raw.split('.')
        if len(parts) != 3:
            return ''
        return '%s-%s-%s' % (parts[2], parts[1], parts[0])

    @staticmethod
    def _privat_is_carry(purpose):
        """Технічний рядок перенесення вхідного залишку — не рух коштів."""
        return (purpose or '').strip().startswith('#ПЕРЕНЕСЕННЯ ЗАЛИШКУ')

    def _privat_file_parse(self, raw_data):
        """Автовизначення формату файлу виписки ПриватБанку та розбір.

        Повертає ``(transactions, opening_balance)`` — вхідний залишок беремо з
        рядка «#ПЕРЕНЕСЕННЯ ЗАЛИШКУ» (None, якщо його немає).

        Підтримка: XLS (BIFF8), XLSX, CSV (Приват24, cp1251), MultiCash (ZIP з
        umsatz.txt/auszug.txt). DBF наразі не підтримується.
        """
        b64 = (raw_data or {}).get('privat_xls_b64', '')
        if not b64:
            return ([], None)
        content = base64.b64decode(b64)

        if content[:4] == b'PK\x03\x04':
            # ZIP: MultiCash (umsatz.txt) або XLSX (xl/…).
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
                umsatz = next((n for n in names
                               if n.lower().endswith('umsatz.txt')), None)
                if umsatz:
                    return self._privat_parse_multicash(
                        zf.read(umsatz).decode('cp1251', 'replace'))
                if any(n.startswith('xl/') for n in names):
                    return self._privat_parse_xlsx(content)
            raise UserError(_(
                'ZIP-файл не схожий ні на MultiCash (umsatz.txt), ні на XLSX.'))
        if content[:4] == b'\xd0\xcf\x11\xe0':
            return self._privat_parse_xls(content)
        if content[:1] in (b'\x03', b'\x30', b'\x83', b'\x8b', b'\xf5', b'\xfb'):
            raise UserError(_(
                'Формат DBF поки не підтримується. Скористайтесь XLS/XLSX/CSV '
                'або MultiCash-випискою з Приват24 Бізнес.'))
        # Інакше — текст (CSV Приват24, cp1251).
        return self._privat_parse_csv(content.decode('cp1251', 'replace'))

    def _privat_parse_xls(self, content):
        """XLS (BIFF8) через xlrd — табличний експорт Приват24 Бізнес."""
        import xlrd
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_index(0)
        rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)]
        return self._privat_parse_table_rows(rows)

    def _privat_parse_xlsx(self, content):
        """XLSX через openpyxl — та сама розкладка колонок, що й XLS."""
        import io
        import openpyxl
        wb = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = [[('' if v is None else v) for v in row]
                for row in ws.iter_rows(values_only=True)]
        return self._privat_parse_table_rows(rows)

    def _privat_parse_table_rows(self, rows):
        """Спільний розбір табличного експорту (XLS/XLSX).

        Колонки: №документа, дата, час, знакова сума, валюта, призначення,
        ЄДРПОУ, контрагент, рахунок к/а, МФО, референс.

        Шапки/інфо-блок і підсумки визначаємо не за назвою колонки (XLSX-експорт
        її не має), а за змістом: транзакція — рядок, де колонка дати містить
        коректну дату ДД.ММ.РРРР. Решта (текст «Дата операції», порожні,
        підсумкові рядки) відсіюється автоматично.
        """
        transactions = []
        opening = None
        for row in rows:
            if len(row) <= PRIVAT_XLS_COL_REF:
                continue
            date = self._privat_date(str(row[PRIVAT_XLS_COL_DATE]))
            if not date:
                continue
            purpose = str(row[PRIVAT_XLS_COL_PURPOSE]).strip()
            if self._privat_is_carry(purpose):
                # Вхідний залишок — не рух коштів.
                opening = self._privat_amount(row[PRIVAT_XLS_COL_AMOUNT])
                continue
            doc = self._privat_cell(row[PRIVAT_XLS_COL_DOC])
            ref = self._privat_cell(row[PRIVAT_XLS_COL_REF])
            transactions.append({
                'id': ref or doc,
                'date': date,
                'amount': self._privat_amount(row[PRIVAT_XLS_COL_AMOUNT]),
                'description': purpose,
                'partner_name': self._privat_cell(row[PRIVAT_XLS_COL_CNTR_NAME]),
                'partner_iban': self._privat_cell(row[PRIVAT_XLS_COL_CNTR_ACC]),
                'partner_edrpou': self._privat_cell(row[PRIVAT_XLS_COL_EDRPOU]),
            })
        return transactions, opening

    def _privat_parse_csv(self, text):
        """CSV Приват24 Бізнес (cp1251, роздільник «;»).

        Колонки: ЄДРПОУ; МФО; Рахунок; Валюта; №документу; Дата; МФО банку;
        Назва банку; Рахунок кор.; ЄДРПОУ кор.; Кореспондент; Сума;
        Призначення платежу.
        """
        import csv
        import io
        C_DOC, C_DATE, C_ACC, C_EDRPOU, C_NAME, C_AMOUNT, C_PURPOSE = \
            4, 5, 8, 9, 10, 11, 12
        reader = csv.reader(io.StringIO(text), delimiter=';', quotechar='"')
        transactions = []
        opening = None
        for idx, row in enumerate(reader):
            if len(row) <= C_PURPOSE:
                continue
            if idx == 0 and 'Дата' in row[C_DATE]:
                continue  # шапка
            date = self._privat_date(row[C_DATE])
            if not date:
                continue
            purpose = (row[C_PURPOSE] or '').strip()
            if self._privat_is_carry(purpose):
                opening = self._privat_amount(row[C_AMOUNT])
                continue
            transactions.append({
                'id': (row[C_DOC] or '').strip(),
                'date': date,
                'amount': self._privat_amount(row[C_AMOUNT]),
                'description': purpose,
                'partner_name': (row[C_NAME] or '').strip(),
                'partner_iban': (row[C_ACC] or '').strip(),
                'partner_edrpou': (row[C_EDRPOU] or '').strip(),
            })
        return transactions, opening

    def _privat_parse_multicash(self, text):
        """MultiCash umsatz.txt (cp1251, «;»).

        Значущі поля: [1] рахунок, [3] дата, [5] призначення, [9] №документа,
        [10] знакова сума; назва контрагента — останнє непорожнє поле (не тег
        {{…}}).
        """
        M_ACC, M_DATE, M_PURPOSE, M_DOC, M_AMOUNT = 1, 3, 5, 9, 10
        transactions = []
        opening = None
        for line in text.splitlines():
            if not line.strip():
                continue
            fields = line.split(';')
            if len(fields) <= M_AMOUNT:
                continue
            date = self._privat_date(fields[M_DATE])
            if not date:
                continue
            purpose = (fields[M_PURPOSE] or '').strip()
            if self._privat_is_carry(purpose):
                opening = self._privat_amount(fields[M_AMOUNT])
                continue
            partner_name = next(
                (f.strip() for f in reversed(fields)
                 if f.strip() and not f.strip().startswith('{{')), '')
            transactions.append({
                'id': (fields[M_DOC] or '').strip(),
                'date': date,
                'amount': self._privat_amount(fields[M_AMOUNT]),
                'description': purpose,
                'partner_name': partner_name,
                'partner_iban': '',
                'partner_edrpou': '',
            })
        return transactions, opening

    def _parse_transactions(self, raw_data):
        """Parse PrivatBank API response into transaction list."""
        self.ensure_one()

        if self.provider == 'privat_xls':
            return self._privat_file_parse(raw_data)[0]

        if self.provider != 'privat':
            return super()._parse_transactions(raw_data)

        api_type = raw_data.get('api_type')

        if api_type == 'autoclient':
            return self._privat_parse_autoclient(raw_data.get('response', {}))
        elif api_type == 'merchant':
            return self._privat_parse_merchant(raw_data.get('response_text', ''))
        else:
            return []

    @staticmethod
    def _privat_api_date(raw):
        """'ДД.ММ.РРРР[ ГГ:ХХ:СС]' → 'РРРР-ММ-ДД'; '' якщо не дата."""
        raw = str(raw or '').strip()[:10]
        try:
            return datetime.strptime(raw, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            return ''

    @staticmethod
    def _privat_uid(item):
        """Унікальний ключ рядка: за документацією — REF+REFN.

        ``ID`` транзакції лишається запасним ключем для відповіді без REF.
        """
        ref = str(item.get('REF') or '').strip()
        if ref:
            return '%s/%s' % (ref, str(item.get('REFN') or '').strip())
        return str(item.get('ID') or item.get('id') or '').strip()

    def _privat_parse_autoclient(self, data):
        """Транзакції API «Автоклієнт» → словники bank_sync.

        Поля за документацією банку: ``SUM`` — сума у валюті рахунку,
        ``TRANTYPE`` — D (списання) / C (надходження), ``DAT_OD`` — дата
        валютування, ``OSND`` — підстава платежу, ``AUT_CNTR_NAM`` /
        ``AUT_CNTR_ACC`` / ``AUT_CNTR_CRF`` — назва, рахунок і ЄДРПОУ
        контрагента, ``PR_PR`` — стан проведення.
        """
        transactions = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get('transactions', []) or data.get('statements', []) or []
        else:
            return []

        for item in items:
            # p – проводиться, t – сторнована, n – забракована: не рух коштів
            # (поки). Відсутнє поле — старий/нестандартний формат, приймаємо.
            state = str(item.get('PR_PR') or '').strip().lower()
            if state and state != PRIVAT_PR_PR_BOOKED:
                continue
            transactions.append({
                'id': self._privat_uid(item),
                'date': (self._privat_api_date(item.get('DAT_OD'))
                         or self._privat_api_date(item.get('DATE_TIME_DAT_OD_TIM_P'))
                         or item.get('TRANDATE') or item.get('date', '')),
                'amount': self._privat_parse_amount(item),
                'description': (item.get('OSND') or item.get('purpose')
                                or item.get('description', '')),
                'partner_name': item.get('AUT_CNTR_NAM') or item.get('CNTR_NAME', ''),
                'partner_iban': item.get('AUT_CNTR_ACC') or item.get('CNTR_ACC', ''),
                'partner_edrpou': item.get('AUT_CNTR_CRF') or item.get('CNTR_CRF', ''),
                'currency': item.get('CCY', ''),
            })

        return transactions

    def _privat_autoclient_balances(self, raw_data):
        """(вхідний, вихідний) залишок періоду з ``/statements/balance``.

        Документація не каже, чи за інтервалом дат приходить один запис на
        рахунок чи по запису на день, і в якому порядку. Тому беремо записи
        свого рахунку, перевіряємо безперервність (вхідний + Σкредит −
        Σдебет = вихідний) у прямому й зворотному порядку і віддаємо залишки
        лише якщо вона сходиться; інакше виписка лишається не звіреною.
        """
        acc = (raw_data.get('acc') or '').replace(' ', '').upper()
        rows = [b for b in (raw_data.get('balances') or [])
                if isinstance(b, dict) and (
                    not acc or str(b.get('acc') or '').replace(' ', '').upper() == acc)]
        if not rows:
            return (None, None)
        amt = self._privat_clean_amount
        turnover = round(sum(amt(b.get('turnoverCred') or 0)
                             - amt(b.get('turnoverDebt') or 0) for b in rows), 2)
        for ordered in (rows, rows[::-1]):
            opening = amt(ordered[0].get('balanceIn') or 0)
            closing = amt(ordered[-1].get('balanceOut') or 0)
            if round(opening + turnover, 2) == round(closing, 2):
                return (opening, closing)
        _logger.warning("PrivatBank Autoclient: balances of %s do not chain, "
                        "statement left unverified", acc)
        return (None, None)

    def _privat_parse_merchant(self, xml_text):
        """Parse Merchant API XML response."""
        import xml.etree.ElementTree as ET

        transactions = []

        try:
            root = ET.fromstring(xml_text)

            for statement in root.findall('.//statement'):
                amount_str = statement.get('cardamount', '0')
                amount = self._privat_clean_amount(amount_str)

                trans = {
                    'id': statement.get('refp', ''),
                    'date': statement.get('trandate', ''),
                    'amount': amount,
                    'description': statement.get('description', ''),
                    'partner_name': '',
                    'partner_iban': '',
                    'partner_edrpou': '',
                }
                transactions.append(trans)

        except ET.ParseError as e:
            _logger.error("PrivatBank: XML parse error: %s", str(e))

        return transactions

    def _privat_parse_amount(self, item):
        """Знакова сума транзакції API «Автоклієнт».

        ``SUM`` — сума у валюті рахунку (``SUM_E`` — еквівалент у гривні,
        лише запасний варіант). Напрям — ``TRANTYPE``: D – дебет (списання,
        «−»), C – кредит (надходження, «+»).

        Для відповіді без ``TRANTYPE`` (не задокументовано) лишаємо колишні
        ознаки DEBIT / BPL / знак у сумі. Вгадування напряму за словами
        призначення прибрано: «оплата» буває й надходженням, а мовчки
        перевернутий знак гірший за явну помилку.
        """
        amount_str = (
            item.get('SUM') or
            item.get('SUMA') or
            item.get('SUM_E') or
            item.get('amount') or
            item.get('cardamount') or
            '0'
        )
        amount = self._privat_clean_amount(amount_str)

        trantype = str(item.get('TRANTYPE', '')).strip().upper()
        if trantype == 'D':
            return -abs(amount)
        elif trantype == 'C':
            return abs(amount)

        debit_flag = item.get('DEBIT')
        if debit_flag is not None:
            return -abs(amount) if str(debit_flag) == '1' else abs(amount)

        bpl = str(item.get('BPL', '')).strip().upper()
        if bpl == 'D':
            return -abs(amount)
        elif bpl == 'C':
            return abs(amount)

        if isinstance(amount_str, str) and amount_str.strip().startswith('-'):
            return -abs(amount)
        if isinstance(amount_str, (int, float)) and amount_str < 0:
            return -abs(amount)

        raise UserError(_(
            'Не вдалося визначити напрям (дебет/кредит) транзакції ПриватБанку '
            '%s: у відповіді немає поля TRANTYPE.') % (
                self._privat_uid(item) or item.get('NUM_DOC') or '?'))

    def _privat_clean_amount(self, amount_str):
        """Clean and convert amount string to float."""
        if isinstance(amount_str, (int, float)):
            return float(amount_str)

        # Remove spaces, currency suffixes, convert comma to dot
        amount_str = str(amount_str).replace(' ', '').replace(',', '.')
        # Remove non-numeric characters except minus and dot
        cleaned = ''.join(c for c in amount_str if c.isdigit() or c in '.-')

        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    def action_test_connection(self):
        """Перевірка токена й рахунку: серверні дати + залишок за сьогодні."""
        self.ensure_one()

        if self.provider != 'privat':
            return super().action_test_connection()

        if not self.sudo().privat_api_token:
            raise UserError(_("Please configure API Token"))

        iban = self._privat_iban()
        settings = self._privat_settings()
        today = fields.Date.context_today(self).strftime('%d-%m-%Y')
        data = self._privat_request('/statements/balance', {
            'acc': iban, 'startDate': today, 'endDate': today,
            'limit': PRIVAT_PAGE_SIZE})
        balances = [b for b in data.get('balances') or []
                    if str(b.get('acc') or '').replace(' ', '').upper() == iban]
        if balances:
            acc_info = balances[-1]
            message = _('Connected! Account: %s, Balance: %s %s') % (
                acc_info.get('acc', 'N/A'),
                acc_info.get('balanceOut', 'N/A'),
                acc_info.get('currency', 'UAH'),
            )
            if settings.get('date_final_statement'):
                message += ' ' + _('Підсумкова виписка є до %s включно.') % (
                    str(settings['date_final_statement'])[:10])
            kind = 'success'
        else:
            message = _(
                'Токен прийнято, але рахунку %s серед рахунків цього '
                '«Автоклієнта» немає. Перевірте IBAN і доступ застосунку API '
                'до рахунку.') % iban
            kind = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success') if kind == 'success' else _('Warning'),
                'message': message,
                'type': kind,
            }
        }
