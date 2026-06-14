# Маркетплейси та прайс-агрегатори

← [Назад до головної](../README.md)

Легенда статусів: ✅ Стабільний · 🟢 Робочий · 🟡 Бета · 📦 Збірка

| Модуль | Версія | Статус | Призначення |
|--------|--------|--------|-------------|
| `l10n_ua_marketplace_base` | 19.0.1.0.0 | 🟢 | Базовий модуль інтеграцій |
| `l10n_ua_marketplace_rozetka` | 19.0.1.0.0 | 🟢 | Rozetka Seller API |
| `l10n_ua_marketplace_prom` | 19.0.1.0.0 | 🟢 | Prom.ua API |
| `l10n_ua_marketplace_hotline` | 19.0.1.0.0 | 🟡 | Hotline.ua (прайс-фід) |
| `l10n_ua_marketplace_priceua` | 19.0.1.0.0 | 🟡 | Price.ua (прайс-фід) |

---

## l10n_ua_marketplace_base — Базовий модуль

| Функція | Метод |
|---------|-------|
| Синхронізація товарів | `sync_products()` |
| Синхронізація залишків | `sync_stock()` |
| Синхронізація цін | `sync_prices()` |
| Імпорт замовлень | `import_orders()` |
| Генерація YML фіду | `generate_yml_feed()` |

---

## l10n_ua_marketplace_rozetka — Rozetka

YML фід для Rozetka, маппінг категорій, імпорт замовлень, оновлення статусів.

## l10n_ua_marketplace_prom — Prom.ua

Фід для Prom.ua, синхронізація через API, імпорт замовлень.

## l10n_ua_marketplace_hotline / l10n_ua_marketplace_priceua

Генерація прайс-фідів для прайс-агрегаторів Hotline.ua та Price.ua.
