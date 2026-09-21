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

62 з 83 модулів встановлюються на чистій БД. Лишається 21 — усі через
три зміни ядра, описані нижче.

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
треба `rec.field.content` (або `bytes(rec.field)`).

### Прибрані поля й моделі

| Було (19.0) | Стало (20.0) |
|---|---|
| `ir.actions.report.report_file` | прибрано |
| `hr.employee.study_school` | прибрано, оголошуємо самі в `l10n_ua_hr_base` |
| `hr.job.contract_type_id`, `hr.contract.type` | `employee_type_id`, `hr.employee.type` |
| `resource.calendar.tz` | прибрано (часовий пояс з компанії/ресурсу) |
| `resource.calendar.schedule_type` | `calendar_type`: `fully_fixed`→`fixed`, `flexible`→`undefined` |
| `resource.calendar.attendance.name` | прибрано |
| `pos.payment.method.is_cash_count` | обов'язкове `type` (`cash`/`bank`/`pay_later`) |

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

## Що лишається

### 1. `hr.leave.type` → `hr.work.entry.type`

Модель типів відпусток злита з типами робочого часу. Наслідки:

* `hr.leave.holiday_status_id` → `work_entry_type_id`;
* нова модель **не має `company_id`** — вона прив'язана до `country_id`.
  Наш `ua_is_default` («показувати за замовчуванням») був у розрізі
  компанії — потрібне рішення: чи переносити його на `res.company`
  окремим Many2one, чи робити один типовий на країну;
* `code` обов'язковий і унікальний у межах країни — нашим 15 типам
  відпусток треба роздати коди;
* `count_as` (`working_time`/`absence`) — для відпусток `absence`.

Блокує: `l10n_ua_hr_holidays`, `l10n_ua_hr_documents`, `l10n_ua_hr_fss`,
`l10n_ua_hr_attendance_sheet`, `l10n_ua_hr_vacation_reserve`,
`l10n_ua_hr_employee_transfer`, `l10n_ua_hr`, `l10n_ua_full`.

### 2. Прибрано `res.bank`

Реквізити банку переїхали в денормалізовані поля `res.partner.bank`
(`bank_name`, `bank_bic`, адреса). Наш довідник МФО (`l10n_ua_bank_sync`,
`res.bank.ua_mfo` + сидовані банки) лишився без моделі-носія.

Потрібне рішення: власна модель довідника МФО (наприклад `l10n_ua.bank`)
з резолвингом `МФО → назва банку` в `res.partner.bank`.

Блокує: увесь банківський стек (`bank_sync`, `bank_privat`, `bank_mono`,
`bank_pumb`, `bank_vst`, `bank_text`, `bank_payment`, `bank_openbanking`,
`bank_currency_sync`), а також `l10n_ua_accounting`,
`l10n_ua_hr_business_trip`, `l10n_ua_full`.

### 3. OCA-залежності `l10n_ua_agreement`

`agreement`, `contract`, `sign_oca` ще не мають гілки 20.0. Модуль
чекає на них (або на заміну ядровим функціоналом).

Блокує: `l10n_ua_agreement`, `l10n_ua_agreement_account`.

## Ще не перевірено

* тести (`--test-enable`) — жодного модуля ще не ганяли;
* читання Binary-полів (`base64.b64decode(rec.field)`) — 44 місця, з них
  частина декодує рядки з JSON і чіпати їх не можна;
* каталоги `migrations/19.0.*` — на гілці 20.0 вони спрацюють при
  оновленні зі старої версії і звертаються до вже прибраних полів;
* `telegram_bot_m2o` — не в переліку l10n_ua, security ще на
  `ir.model.access.csv`.
