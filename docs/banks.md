# Банки та платежі

← [Назад до головної](../README.md)

![Bank Sync](../diagrams/bank_sync.svg)

Легенда статусів: ✅ Стабільний · 🟢 Робочий · 🟡 Бета · 📦 Збірка

| Модуль | Версія | Статус | Призначення |
|--------|--------|--------|-------------|
| `l10n_ua_bank_sync` | 19.0.1.0.0 | 🟢 | Базова синхронізація з банками (конфіг, завдання, виписки, транзакції, правила співставлення) |
| `l10n_ua_bank_privat` | 19.0.1.0.0 | 🟢 | ПриватБанк (Автоклієнт Privat24 Business + legacy Merchant API) |
| `l10n_ua_bank_mono` | 19.0.1.2.0 | 🟢 | monobank (Personal API для ФОП + Corporate API для юросіб) |
| `l10n_ua_bank_mono_payment` | 19.0.1.0.0 | 🟡 | monobank Corporate API: платіжні доручення на підпис у застосунку |
| `l10n_ua_bank_mono_hr` | 19.0.1.0.0 | 🟡 | monobank Corporate API: зарплатні відомості, зарплатні контакти, розрахункові листи |
| `l10n_ua_bank_vst` | 19.0.1.0.0 | ✅ | VST Bank / Банк Восток (імпорт виписки iBank 2 UA CSV) + тести |
| `l10n_ua_bank_novapay` | 19.0.1.0.0 | ✅ | NovaPay (API бізнес-кабінету, виписка рахунку) + тести |
| `l10n_ua_bank_currency_sync` | 19.0.1.0.0 | ✅ | Курси валют (НБУ, ПриватБанк, monobank) + тести |
| `l10n_ua_payment_link` | 19.0.1.0.0 | 🟢 | QR-посилання НБУ + еквайринг monobank |

---

## l10n_ua_bank_sync — Базовий модуль

Залежності: `l10n_ua_account_base`, `mail`.

Фундамент для банківських інтеграцій. Провайдерні модулі (`_privat`, `_mono`, `_vst`, `_openbanking`) наслідують конфіг і реалізують виклики конкретних API/файлів.

**Архітектура виписок (рефактор на native Odoo):** виписка формується **в процесі імпорту** як унікальна рідна сутність `account.bank.statement` — з метаданими джерела (дата, тип file/api/manual, назва файлу/провайдер) і балансами **з джерела** (контроль повноти `balance_end == balance_end_real`; без балансів — виводиться й позначається не звіреною). Рядки — рідні `account.bank.statement.line` (з `l10n_ua_import_uid` для дедупу), контрагент підбирається при імпорті за ЄДРПОУ/IBAN. Звірка та проводки — **рідним механізмом Odoo** (`account.reconcile.model` + reconcile-віджет). Кастомні моделі `l10n_ua.bank.statement` / `l10n_ua.bank.transaction` / `l10n_ua.bank.match.rule` та «Generate Statement» (постфактумне формування) **видалені**.

| Модель | Призначення |
|--------|-------------|
| `l10n_ua.bank.sync.config` | Конфігурація підключення (провайдер, журнал, рахунок). Точки розширення: `_fetch_from_bank()`, `_parse_transactions()`, `_extract_balances()`, `_source_type()` |
| `l10n_ua.bank.sync.job` | Завдання синхронізації `draft → fetching → fetched → processing → done / error`. Зберігає сирий payload; `_create_native_statement()` формує рідну виписку при обробці; `bank_statement_id` — посилання на неї |
| `account.bank.statement` (+метадані) | Рідна виписка з `l10n_ua_source_type/_ref`, `l10n_ua_import_date`, `l10n_ua_balance_verified/_ok` |

Розширення: `res.bank` (код МФО), `res.partner.bank` (валідація IBAN), `account.journal` (прив'язка конфігу синхронізації).

Тести: `test_native_statement.py` (виписка+метадані при імпорті, баланс derived/verified/mismatch, ідемпотентність, підбір контрагента), `test_auto_sync.py`, `test_multicompany.py`.

---

## l10n_ua_bank_privat — ПриватБанк

Залежності: `l10n_ua_bank_sync`.

Наслідує `l10n_ua.bank.sync.config`, додає провайдера `privat`. Реалізовано два реальні шляхи отримання виписок:

- **Автоклієнт (Privat24 Business)** — `_privat_fetch_autoclient()`, `GET https://acp.privatbank.ua/api/statements/transactions` із заголовком `token` та параметрами `startDate/endDate/acc`.
- **Legacy Merchant API** — `_privat_fetch_merchant()`, `https://api.privatbank.ua/p24api/rest_fiz`, XML-запит `cmt` за номером картки (для старих інтеграцій).

Вибір гілки — за наявністю токена або merchant-облікових даних. Підтримка корпоративних карток.

Тести: відсутні.

---

## l10n_ua_bank_novapay — NovaPay

Залежності: `l10n_ua_bank_sync`.

Наслідує `l10n_ua.bank.sync.config`, додає провайдера `novapay`. Працює з API бізнес-кабінету NovaPay — SOAP 1.1, `https://business.novapay.ua/Services/ClientAPIService.svc` (адресу можна перевизначити параметром `l10n_ua_bank_novapay.api_url`):

- **Авторизація** — `UserAuthenticationJWT` за логіном, refresh-токеном і відкритим сертифікатом (кабінет: Система → Налаштування → API). Refresh-токен **одноразовий**: кожна авторизація повертає нову пару токен/сертифікат. Її зберігає окрема модель `l10n_ua.bank.novapay.session` **власним курсором** — відкат основної транзакції (помилка розбору виписки) не губить щойно виданий токен. JWT кешується до закінчення терміну дії; рядок сесії блокується `FOR UPDATE`, щоб паралельні синхронізації не витратили токен двічі.
- **Рахунок** — `GetClientsList` + `GetAccountsList`: ID рахунку NovaPay визначається за IBAN банківського журналу й запам'ятовується (`novapay_client_id`, `novapay_account_id`).
- `_fetch_from_bank()` → `GetAccountExtract` (дати `дд.мм.рррр`) + `GetAccountTurns` для залишків.
- `_parse_transactions()` — документи `Docs` виписки: сума з атрибута `Amount` без знака, напрям визначається за тим, на якій стороні наш IBAN (`DebitCodeIBAN` / `CreditCodeIBAN`; запасний варіант — ЄДРПОУ компанії). Контрагент: назва, IBAN, ЄДРПОУ протилежної сторони. Унікального ID документа API не дає, тому ключ дедуплікації — хеш реквізитів (номер, дата, сума, обидва IBAN, призначення).
- `_extract_balances()` — вхідний залишок першого дня та вихідний останнього з оборотів.

⚠️ На реальному кабінеті **не перевірено** (потрібні бойові логін/токен): склад полів `Docs` узято з відкритих клієнтів API, а не з офіційної інструкції; не підтверджено формат `expiration` JWT і чи повертає `GetAccountTurns` дні без руху.

**Тести: наявні** — `tests/test_novapay.py`, 21 сценарій на моках SOAP (ротація й кеш токена, пошук рахунку, напрям операцій, дедуп, баланс, повний цикл завдання).

---

## l10n_ua_bank_mono — monobank

Залежності: `l10n_ua_bank_sync`.

Наслідує `l10n_ua.bank.sync.config`, додає провайдера `mono`. Реальна інтеграція з Personal API monobank:

- `_fetch_from_bank()` → `GET https://api.monobank.ua/personal/statement/{account}/{from}/{to}` із заголовком `X-Token`; обмеження API у 31 день та обробка `429` (rate limit).
- `_mono_get_default_account()` — автовизначення гривневого рахунку (валюта 980) через `/personal/client-info`.
- `_parse_transactions()` — суми з копійок у гривні, знак задає напрям (Дт/Кт), витягує назву/IBAN/ЄДРПОУ контрагента.
- `action_test_connection()`, `action_fetch_accounts()` — перевірка токена та перелік рахунків із балансами.

⚠️ Webhook: поле `mono_webhook_url` обчислюється (`/l10n_ua_bank_mono/webhook/<id>`) і є прапорець `mono_webhook_active`, але **контролер webhook у модулі не реалізований** — real-time оновлення поки заглушка. Синхронізація працює через опитування (fetch job).

Тести: відсутні.

---

## l10n_ua_bank_mono_payment — платежі через monobank Corporate API (#352)

Залежності: `l10n_ua_bank_mono`, `l10n_ua_bank_payment` (auto_install).

У платіжному дорученні (`l10n_ua.bank.payment`) з'являється «Спосіб передачі»: файл із КЕП (як було) або **monobank API**. Підключення Corporate API визначається за IBAN рахунку платника. «Надіслати в monobank» викликає `POST /ext/v1/payment/prepare` для кожного рядка: `externalReference` — ідентифікатор рядка в цій базі, `idempotency-key` — UUID v5 від референсу й тіла платежу (повтор після таймауту не створить дубль). Платіж підписує директор у застосунку або web-кабінеті monobank, КЕП в Odoo не потрібен.

- Бюджетні платежі: код виду сплати (`payCode`), додаткова інформація, фактичний платник (`ultimateDebit`); призначення формується за форматом документації `{payCode} {additionalInfo} ЄДРПОУ {ЄДРПОУ компанії}`.
- Помилка банку по рядку зберігається на рядку, решта платежів лишаються підготовленими; повторне надсилання відправляє лише невідправлені.
- Стан (`GET /ext/v1/payment/{id}/state`): `DRAFT` → очікує підпису, `DECLINED` → відхилено, `IN_STATEMENT` → у виписці. Рядок виписки з тим самим `externalReference` прив'язується до платежу автоматично (під час імпорту виписки або оновлення стану). Cron щогодини.

**Тести:** `tests/test_mono_payment.py` (моки `requests`).

---

## l10n_ua_bank_mono_hr — зарплата через monobank Corporate API (#352)

Залежності: `l10n_ua_bank_mono`, `l10n_ua_hr_salary` (auto_install).

- **Зарплатна відомість.** У майстрі «Зарплатний файл у банк» формат «monobank API» створює чернетку `l10n_ua.mono.salary.registry` (тип — зі списку `/ext/v1/payments/salary/registries/types`). «Надіслати в monobank» відправляє одержувачів пакетами по 1000 (`POST /ext/v2/payments/salary/registries`, один `registryReference`), потім `…/finalize`. Невдалий пакет зупиняє відправку без втрати попередніх: наступна спроба продовжує з нього. Статус (`SAVED` … `SUCCEEDED`/`FAILED`) опитує cron, `declineReason` пишеться в чатер.
- **Зарплатні контакти.** Кнопка «Синхронізувати зарплатні контакти»: пошук за РНОКПП/номером паспорта (`/salary-contacts/search`), створення відсутніх, звіт про розбіжність IBAN (не перезаписується).
- **Розрахункові листи в застосунку.** `l10n_ua.mono.payslip.import` (кнопка «Листи в monobank» у відомості): нарахування, ПДФО, ВЗ, утримання, до виплати — як `attributes` у `/ext/v1/payslips/batch` пакетами по 1000; «Опублікувати працівникам» (`/payslip-imports/send`); `CONTACT_NOT_FOUND` показуються списком; PDF листа — кнопкою в рядку листка.

**Тести:** `tests/test_mono_hr.py` (моки `requests`).

---

## l10n_ua_bank_vst — VST Bank (iBank 2 UA)

Залежності: `l10n_ua_bank_sync`.

Файловий провайдер VST Bank (Банк Восток) — `provider = 'vst'`. Банк не опитується по API; виписка експортується з iBank 2 UA у CSV («Виписки по поточним рахункам», windows-1251, роздільник «;», з шапкою). Майстер **Імпорт виписки iBank 2 UA** (`l10n_ua.bank.vst.import`) приймає CSV-файл, створює завдання `l10n_ua.bank.sync.job` (`raw_payload = {'csv': ...}`, стан `fetched`) і запускає `action_process`. `_parse_transactions` розбирає рядки у стандартні транзакції: Дебет → від'ємна сума (Дт), Кредит → додатна (Кт), дата операції, кореспондент (назва / IBAN / ЄДРПОУ), призначення платежу — далі штатний конвеєр bank_sync (правила співставлення, проводки).

Зарплатний реєстр iBank 2 UA формується майстром зарплатного файлу у `l10n_ua_hr_salary` (формат `ibank2`). Банк доданий у `res.bank` (МФО 307123).

**Тести: наявні** — `tests/test_vst_import.py`, 5 сценаріїв (Дт/Кт зі знаком, пропуск шапки/порожніх, делегування іншим провайдерам, майстер→завдання).

---

## l10n_ua_bank_currency_sync — Курси валют

Залежності: `base`, `account`, `l10n_ua_bank_sync` (для меню «Банк UA»).

Синхронізація курсів із трьох джерел через модель `res.currency.rate.provider`:

- **НБУ** — `https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json&date=YYYYMMDD` (офіційний курс).
- **ПриватБанк** — `https://api.privatbank.ua/p24api/pubinfo?json&exchange&coursid=N` (тип курсу налаштовується).
- **monobank** — `https://api.monobank.ua/bank/currency`.

Особливості: коректний перерахунок крос-курсу для компаній із не-гривневою валютою (`_uah_per_company_unit`, `_rate_vals`), запис у `res.currency.rate`, ручна та планова (cron) синхронізація, майстер синхронізації, історія курсів.

**Тести: наявні** — `tests/test_cross_rate.py`, 8 сценаріїв (реципрокність гривні, крос-курс для не-UAH компанії, ігнорування «сирих» котирувань, крос-курс monobank тощо).

---

## l10n_ua_payment_link — QR-платежі та еквайринг

Залежності: `l10n_ua_account_base`, `sale`.

Генерація платіжних посилань для рахунків (`account.move`) та замовлень (`sale.order`):

- **QR НБУ** — `nbu_payment_link` формується за шаблоном (`ir.config_parameter l10n_ua.nbu_qr_template`, Постанова НБУ №11 від 01.02.2021), кодується `base64url`, посилання `https://bank.gov.ua/qr/<payload>`. QR-код рендериться у SVG data-URI (`qrcode`).
- **Еквайринг monobank** — `action_create_mono_link()`: `POST https://api.monobank.ua/api/merchant/invoice/create` із токеном журналу (`mono_acquiring_token`), передає позиції рахунку та `webHookUrl`; зберігає `mono_payment_link` (pageUrl) і `mono_invoice_id`.
- **Webhook підтвердження оплати** — контролер `/l10n_ua_payment_link/mono/webhook`: за `invoiceId` і `status == 'success'` знаходить замовлення/рахунок та проводить оплату.

Розширення: `account.journal` (токен еквайрингу), `res.config.settings`, друкована форма рахунку з QR (`report_invoice_inherit`).

Тести: відсутні.
