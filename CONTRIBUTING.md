# Внесок у проєкт (CONTRIBUTING)

Короткі обов'язкові правила для розробки модулів `l10n_ua_*` (Odoo 19).
Кодові конвенції Odoo 19 (нові `models.Constraint`, `type='jsonrpc'`, `list`-view,
пошукові view тощо) — у [`CLAUDE.md`](../CLAUDE.md).

## Мультикомпанійність (обов'язково)

> **Кожна нова модель зі збереженим `company_id` мусить мати глобальне
> multi-company `ir.rule` + тест ізоляції.**

Без правила записи моделі **видимі через усі компанії**, включно з не-UA
(див. [issue #178](https://github.com/NadozirnySvyatoslav/l10n_ua/issues/178)).

**Правило** — у `security/multicompany_security.xml` модуля, що **дефінує** модель
(не того, що лише `_inherit`ить):

```xml
<record id="<model_underscored>_company_rule" model="ir.rule">
    <field name="name">Назва: multi-company</field>
    <field name="model_id" ref="model_<model_underscored>"/>
    <field name="global" eval="True"/>
    <field name="domain_force">
        ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]
    </field>
</record>
```

- `model_<model_underscored>` — ім'я моделі з крапками→підкресленнями
  (`l10n_ua.vat.declaration` → `model_l10n_ua_vat_declaration`).
- Зареєструвати файл у `__manifest__.py` `data` **одразу після** `security/ir.model.access.csv`.
- Якщо `company_id` — **related без `store=True`**: фільтрувати через шлях батька
  (`('parent_id.company_id', 'in', company_ids)`), бо SQL не бачить незбережене поле.
- **Не потрібно** правило для: transient-моделей (візарди/звіти), abstract-моделей,
  `.line`-дітей (покриті правилом батька), спільних довідників без `company_id`
  (КЕКВ/КВЕД/відділення доставки тощо).

**Тест ізоляції** (шаблон — [`l10n_ua_account_vat/tests/test_multicompany.py`](l10n_ua_account_vat/tests/test_multicompany.py)):
створити UA + не-UA компанію та користувача, обмеженого не-UA компанією з
доступовою групою моделі; переконатися, що він **не бачить** запис UA-компанії, але
**бачить** власний.

### Odoo 19 — пастки в цих тестах/правилах
- `res.users` поле груп — **`group_ids`**, не `groups_id`.
- Поле `ir.rule.global` читати як **`rule['global']`** (`global` — ключове слово
  Python; `rule.global_` **не існує**).

## Меню

Нові пункти меню — за реєстром і конвенціями у
[`docs/menu_registry.md`](docs/menu_registry.md): правило «власний апп чи вкладення»,
діапазони `sequence`, гейтинг за роллю. Пам'ятай: **гейтинг листків/дій**, не лише
кореня, і меню **не ховаються за активною компанією** (обмеження Odoo — див.
[`docs/menu_architecture.md`](docs/menu_architecture.md)).

## Тести

Перед PR — прогнати оновлення модуля з тестами:

```bash
./venv311/bin/odoo -c <conf> -d <db> -u <module> --test-enable \
    --test-tags /<module>:<TestClass> --stop-after-init
```

Не називати тест-метод `test_sequence` — Odoo 19 мовчки пропускає всі тести модуля.

## Опис модуля для Odoo Apps

Сторінку модуля в Apps будує `static/description/index.html`. Правила:

- **Файл — повний HTML-документ із кодуванням.** Без `<meta charset="UTF-8">` Apps
  читає файл як Latin-1, і українська стає «ÐÐ¾Ð³Ð¾…» (10.11.2026 так зламались 13 модулів).
  Шаблон:

  ```html
  <!DOCTYPE html>
  <html lang="uk">
  <head>
      <meta charset="UTF-8">
  </head>
  <body>
  <section>…</section>
  </body>
  </html>
  ```

- Поруч `icon.png` (128×128) — без нього в Apps стоїть порожня іконка.
- Картинки — відносні шляхи до файлів у `static/description/` (Apps переписує їх на CDN).
- Перед PR, що зачіпає `static/description/`:

  ```bash
  python3 docs/tools/apps_check/check_descriptions.py
  ```

  Помилка = PR не зливаємо. Ця ж перевірка працює в GitHub Actions на кожен PR.
- Після публікації відкрий сторінку `https://apps.odoo.com/apps/modules/<версія>/<модуль>`
  і перевір, що текст читається.
