# Українська локалізація Odoo 19

Комплексне рішення для управління бізнесом та установами в Україні: бухгалтерія, податки, банки, ПРРО, доставка, маркетплейси, HR/зарплата, а також галузеві рішення для бюджетних, освітніх і медичних установ.

> Цей файл — **головний індекс**. Деталі по кожному напрямку — у відповідних документах у теці [`docs/`](docs/).

---

## Огляд напрямків

**Всього: 67 модулів** для Odoo 19.

| Напрямок | Модулів | Статус | Детальна документація |
|----------|:-------:|:------:|-----------------------|
| Базові та бухгалтерія | 5 | ✅ | [docs/core_accounting.md](docs/core_accounting.md) |
| Податки та звітність | 6 | ✅ | [docs/taxes.md](docs/taxes.md) |
| Банки та платежі | 5 | 🟢 | [docs/banks.md](docs/banks.md) |
| ПРРО (фіскалізація) | 2 | 🟢 | [docs/prro.md](docs/prro.md) |
| Доставка | 4 | 🟢 | [docs/delivery.md](docs/delivery.md) |
| Маркетплейси | 5 | 🟢 | [docs/marketplaces.md](docs/marketplaces.md) |
| Ціни постачальників | 6 | 🟢 | [docs/supplier_prices.md](docs/supplier_prices.md) |
| HR та зарплата (1С:ЗУП) | 13 | ✅ | [docs/hr.md](docs/hr.md) |
| Бюджетні установи | 8 | 🟡 | [docs/budget.md](docs/budget.md) |
| Заклади освіти | 6 | 🟡 | [docs/education.md](docs/education.md) |
| Заклади охорони здоров'я | 6 | 🟡 | [docs/medicine.md](docs/medicine.md) |
| Інше (Telegram-бот) | 1 | 🟢 | — |

### Легенда готовності

| Статус | Значення |
|--------|----------|
| ✅ **Стабільний** | Функціонал реалізований і покритий тестами; готовий до використання |
| 🟢 **Робочий** | Функціонал реалізований; тести часткові або відсутні |
| 🟡 **Бета** | Базовий каркас, напрямок в активній розробці |
| 📦 **Збірка** | Мета-модуль, що встановлює стек залежностей |

> Готовність напрямку у таблиці — за найслабшим суттєвим модулем. У детальних документах статус наведено окремо для кожного модуля.

---

## Архітектура модулів

![Module Architecture](diagrams/full_architecture.svg)

Усі діаграми — у теці [`diagrams/`](diagrams/) (`.puml` + `.svg`): загальна архітектура, структура меню, HR, модель даних, процеси ПРРО, банків, прийому на роботу, розрахунку зарплати тощо.

---

## Швидке встановлення

### ФОП (мінімум)
```bash
odoo-bin -d <db> -i l10n_ua_account_base,l10n_ua_tax,l10n_ua_fop,l10n_ua_bank_sync --stop-after-init
```

### Повна бухгалтерія
```bash
odoo-bin -d <db> -i l10n_ua_accounting,l10n_ua_tax,l10n_ua_account_vat,l10n_ua_assets,l10n_ua_tax_cabinet --stop-after-init
```

### HR + зарплата
```bash
odoo-bin -d <db> -i l10n_ua_hr --stop-after-init
```

### ПРРО + банки
```bash
odoo-bin -d <db> -i l10n_ua_prro_checkbox,l10n_ua_bank_privat,l10n_ua_bank_mono --stop-after-init
```

### E-commerce (доставка + маркетплейси)
```bash
odoo-bin -d <db> -i l10n_ua_delivery_novaposhta,l10n_ua_marketplace_rozetka --stop-after-init
```

### Галузеві збірки
```bash
# Бюджетна установа
odoo-bin -d <db> -i l10n_ua_budget --stop-after-init
# Заклад освіти
odoo-bin -d <db> -i l10n_ua_education --stop-after-init
# Заклад охорони здоров'я
odoo-bin -d <db> -i l10n_ua_medecin --stop-after-init
# Все одразу
odoo-bin -d <db> -i l10n_ua_full --stop-after-init
```

### Оновлення
```bash
odoo-bin -d <db> -u <module_name> --stop-after-init
```

---

## Налаштування компанії

1. **Налаштування → Компанії → [Ваша компанія]**
2. Вкладка **«Ukrainian Tax Settings»**:
   - Організаційно-правова форма (ФОП, ТОВ, тощо)
   - Податкова інспекція (ДПІ)
   - Група ФОП та ставка (якщо ФОП)
   - Коди діяльності (КВЕД)

---

## Контакти

**Автори:** Святослав Надозірний, Ярослав Кравець
**Website:** https://many2one.online

## Ліцензія

LGPL-3.0
