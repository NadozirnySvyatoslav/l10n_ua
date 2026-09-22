# Портування на Odoo 20

Гілка `20.0`. Робоче дерево — `~/Projects/1C to Odoo/odoo_addons-20`
(git worktree), гілка `19.0` лишається в `odoo_addons` і живе своїм життям.

## Оточення

| | 19.0 | 20.0 |
|---|---|---|
| код Odoo | `~/Projects/odoo-19` | `~/Projects/odoo-20` |
| addons_path | `addons-extra` | `addons-ua` (лише наші 82 модулі) |
| конфіг | `odoo.conf` | `odoo-ua.conf` (порт 8079) |
| БД | `odoo19ndev` | `odoo20_ua` |
| Python | 3.11 (`venv311`) | 3.14 |

```bash
cd ~/Projects/odoo-20
./venv/bin/python ./odoo-bin -c odoo-ua.conf -d odoo20_ua -i <module> --stop-after-init
```

Зовнішні залежності Python (`httpx h2 openpyxl paramiko qrcode xlrd`)
доставлені у `~/Projects/odoo-20/venv`.

## Стан

**81 з 83 модулів встановлюються на чистій БД, тести зелені: 0 failed,
0 error(s) of 1600 tests.** Лишаються `l10n_ua_agreement` і
`l10n_ua_agreement_account` — чекають на гілку 20.0 в OCA
(`agreement`, `contract`, `sign_oca`).

Прогін тестів:

```bash
cd ~/Projects/odoo-20
./venv/bin/python ./odoo-bin -c odoo-ua.conf -d odoo20_ua \
  -u <список модулів> --stop-after-init --test-enable \
  --test-tags /l10n_ua_account_base,/l10n_ua_...
```

Тестовій базі потрібен план рахунків (частина тестів шукає рахунки за
`account_type`): `env['account.chart.template'].try_loading('generic_coa',
company=company, install_demo=False)`.

## Зміни ядра Odoo 20, які вже відпрацьовані

### ir.model.access + ir.rule → ir.access

Обидві моделі прибрані, натомість одна `ir.access`:

* `security/ir.model.access.csv` → `security/ir.access.csv`,
  колонки `perm_read/write/create/unlink` → одна `operation`
  (підмножина `crud`, порядок саме c-r-u-d) плюс нова колонка `domain`;
* запис **з** `group_id` — це *permission*, записи різних груп
  **об'єднуються** (OR);
* запис **без** `group_id` — це *restriction*, вони **перетинаються**
  (AND). Сюди лягли всі колишні глобальні мультикомпанійні `ir.rule`:
  `domain_force` → `domain`, поле `global` прибрано, додано
  `operation="crud"`.

> **Пастка.** Колишнє `ir.rule` з групами *звужувало* доступ. У Odoo 20
> окремий permission-запис із доменом нічого не звужує — він додає
> дозвіл, і порожній домен сусіднього рядка з'їдає обмеження. Тому
> домен такого правила треба **вливати в domain відповідного рядка**
> `ir.access.csv` (усіх рядків того ж моделі-групи та груп, що її
> імплікують), а не лишати окремим записом.

### Бінарні поля

Binary-поля тепер тримають сирі байти в обгортці `BinaryValue`.
`base64.b64encode(...)` повертає `bytes` — запис таких байтів падає з
`TypeError: use BinaryValue instead of bytes`. Приймаються:

* `BinaryBytes(raw_bytes, filename='...')` — канонічно, `from odoo.tools import BinaryBytes`;
* base64-**рядок** (`.decode()`) — сумісність із RPC, використано у порті.

Читання поля повертає `BinaryValue`: замість `base64.b64decode(rec.field)`
треба `rec.field.content` (або `bytes(rec.field)`), а щоб віддати вміст
у base64 — `rec.field.to_base64()`.

### Прибрані поля й моделі

| Було (19.0) | Стало (20.0) |
|---|---|
| `ir.actions.report.report_file` | прибрано |
| `hr.employee.study_school` | прибрано, оголошуємо самі в `l10n_ua_hr_base` |
| `hr.job.contract_type_id`, `hr.contract.type` | `employee_type_id`, `hr.employee.type` |
| `hr.leave.holiday_status_id`, `hr.leave.type` | `work_entry_type_id`, `hr.work.entry.type` |
| `hr.leave.type.time_type` | `hr.work.entry.type.count_as` (`working_time`/`absence`) |
| `account.payment.state`: `posted`/`in_process`/`sent` | `paid`/`reconciled` |
| `t-esc`, `t-raw` у QWeb | `t-out` (директиви `esc`/`raw` прибрані, мовчки нічого не виводять) |
| `hr.version.contract_date_start` (group) | `hr.group_hr_manager` → `hr.group_hr_user` |
| `resource.calendar.tz` | прибрано (часовий пояс з компанії/ресурсу) |
| `resource.calendar.schedule_type` | `calendar_type`: `fully_fixed`→`fixed`, `flexible`→`undefined` |
| `resource.calendar.two_weeks_calendar`, `attendance.week_type` | `calendar_type='variable'` + recurrency |
| `resource.calendar.attendance.name` | прибрано |
| `resource.calendar.leave_ids` | `copy=False` — копіювати свята явно |
| `pos.payment.method.is_cash_count` | обов'язкове `type` (`cash`/`bank`/`pay_later`) |
| `res.company.company_registry`, `res.partner.company_registry` | прибрано — у нас `edrpou` |
| `res.partner.company_type` | прибрано (лишився обчислюваний `is_company`) |
| `res.partner.bank.acc_number` | `account_number` — **зберігається з пробілами**, сирий IBAN у `sanitized_account_number` |
| `res.partner.bank.bank_id`, `res.bank` | прибрано (МФО беремо з IBAN, назву — з `bank_name`) |
| `stock.move.product_uom` | `uom_id` (на sale/account лініях лишається `product_uom_id`) |
| `ir.config_parameter.get_param/set_param` | `get_str/get_bool/get_int/get_float` і `set_*` |
| `mail.message.tracking_value_ids`, `mail.tracking.value` | у окремому модулі `mail_tracking` |

### Тихі зміни поведінки

* **`Char` більше не обрізає значення до `size`** — задовге значення тепер
  падає в Postgres (`StringDataRightTruncation`) замість того, щоб мовчки
  вкоротитись і дійти до `@api.constrains`.
* **Копія дописує « (copy)»** до будь-якого `Char` із назвою `name`
  (`mark_as_copy`), тож `record.copy()` треба передавати `name` явно, якщо
  назва має лишитись тією самою.
* **`.new()` на абстрактній моделі заборонено** (`assert not self._abstract`)
  — для тестів домішки годиться `browse(1)`.
* **IBAN зберігається відформатованим** (`UA21 3223 …`), тому все, що йде у
  файл для банку, має брати `sanitized_account_number` або чистити пробіли.
* **`t-esc` мовчки нічого не виводить**: директиви немає в
  `ir_qweb._directives_eval_order`, тож друкована форма рендериться з
  порожніми клітинками й жодної помилки. Скрізь `t-out`.
* **Курс валюти діє з наступного дня**: `res.currency._get_rates` шукає
  `('name', '<', date)` замість `<=` (Odoo 19), тобто курс НБУ за 30.06
  застосується лише 01.07. Для сум, прив'язаних до дати документа,
  використовуйте `res.currency._l10n_ua_convert` з `l10n_ua_company_base`.
* **Selection не приймає `''`** — порожнє значення тепер тільки `False`.
* **`Char(size=N)`** більше не обрізає — задовге значення падає в Postgres.
* **Відпустку, створену Time Off Officer'ом, Odoo 20 одразу затверджує**
  (`hr_holidays._process_auto_approve_activities`), а затверджену вже не
  дає правити за датами. Раніше авто-затвердження було тільки для
  `leave_validation_type='no_validation'`.
* **Рахунок типу `asset_cash`** при створенні родить банківський журнал,
  а два журнали однієї компанії стикаються поштовим аліасом; при
  завантаженні плану рахунків це вимикає контекст `chart_template_load`.

### Якорі xpath, що зникли з виглядів ядра

| Вигляд | Було | Стало |
|---|---|---|
| `base.view_res_partner_filter` | `filter[@name='type_company']` | `filter[@name='filter_vat_set']` |
| `hr.view_employee_tree` | `field[@name='job_id']` | `field[@name='job_title']` |
| `hr.view_employee_filter` | `filter[@name='my_team']` | `filter[@name='inactive']` |
| `hr.view_employee_form` | `separator[@name='schedule']` | `group[@name='schedule']` |
| `hr.view_employee_form` | `div[@class='o_address_format']` | `div[hasclass('o_address_format')]` |

`hasclass()` замість `@class='...'` — ядро дописує класи (`o_hr_address`),
і точне порівняння перестає збігатися.

## Дві великі заміни моделей

### `hr.leave.type` → `hr.work.entry.type`

Модель типів відпусток злита з типами робочого часу. Наслідки:

* `hr.leave.holiday_status_id` → `work_entry_type_id`, ключ контексту
  `default_holiday_status_id` → `default_work_entry_type_id`;
* нова модель **не має `company_id`** — вона прив'язана до `country_id`.
  Тому:
  * `ua_is_default` («показувати за замовчуванням») переїхав на
    компанію — `res.company.l10n_ua_default_leave_type_id`. Один Many2one
    замість прапорця з ручним зняттям конфліктів: унікальність тепер
    випливає з самого поля, і вибір однієї компанії не чіпає сусідів;
  * кнопки «Імпортувати види відпусток» на компанії більше немає —
    15 видів приходять із даними модуля на всі компанії країни;
  * у генераторі балансів зник обхід «чужих» пар «працівник — вид»;
* `code` обов'язковий і унікальний у межах країни — наші види дістали
  `UA_VAC_*`/`UA_SICK` плюс тризначний `display_code`;
* `time_type` → `count_as` (`working_time`/`absence`).

### Прибрано `res.bank` → `l10n_ua.bank`

Реквізити банку переїхали в денормалізовані поля `res.partner.bank`
(`bank_name`, `bank_bic`, адреса), а `bank_id` зник зовсім.

Довідник МФО тепер наш: модель `l10n_ua.bank` у `l10n_ua_account_base`
(меню «Ukraine → Directories → Banks (MFO)»), а `res.partner.bank` дістав
обчислювані `l10n_ua_mfo` (МФО з IBAN, позиції 5-10) і `l10n_ua_bank_id`
(пошук по МФО, ручний вибір не затирається) та `l10n_ua_bank_name` для
друкованих форм.

### Лишається: OCA-залежності `l10n_ua_agreement`

`agreement`, `contract`, `sign_oca` ще не мають гілки 20.0. Модуль
чекає на них (або на заміну ядровим функціоналом).

Блокує: `l10n_ua_agreement`, `l10n_ua_agreement_account`.

## Міграції

Каталоги `migrations/19.0.*` перейменовані на `20.0.*`: версії модулів тепер
`20.0.x`, і скрипт у каталозі зі старим номером просто не спрацював би при
оновленні. Скрипти мають бути ідемпотентними — база, що вже пройшла
відповідну міграцію на гілці 19.0, пройде її ще раз.

## Ще не перевірено

* `telegram_bot_m2o` — не в переліку l10n_ua, security ще на
  `ir.model.access.csv`;
* нічого не перевірено в браузері — тести покривають лише серверну
  частину, а `t-esc` показав, що саме такі поламки тести не ловлять,
  якщо не рендерити звіт;
* `l10n_ua.bank` має лише 10 банків; повний довідник МФО веде НБУ —
  потрібен імпорт.
