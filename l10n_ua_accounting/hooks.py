"""Install-time fixups that a data file cannot express."""

MODULE = 'l10n_ua_accounting'


def reload_module_terms(env):
    """Перезавантажити переклади модуля, перетираючи наявні значення.

    Потрібно у двох випадках, і обидва не покриваються звичайним завантаженням
    i18n:

    * **Перейменування рідного меню.** Ядро постачає власний переклад
      `account.menu_finance` → «Виставлення рахунків», і він потрапляє в базу
      раніше за наш (account — залежність, тож вантажиться першим).
    * **Зміна власного підпису між релізами.** Скажімо, «Звіт про фін.
      результати (Форма №2)» → «Доходи і витрати (P&L)».

    В обох випадках ключ мови в базі вже є, а імпортер зливає значення як
    `t.value || m.name`, тобто наявне значення перемагає, якщо сервер
    запущено без прапорця i18n-overwrite. Тому після встановлення та після
    оновлення версії ми свідомо перечитуємо файли перекладу цього модуля з
    overwrite: єдиним джерелом правди лишається `i18n/uk_UA.po`.
    """
    langs = [
        code
        for code, _name in env['res.lang'].get_installed()
        if code != 'en_US'
    ]
    if not langs:
        return
    env['ir.module.module']._load_module_terms([MODULE], langs, overwrite=True)


def post_init_hook(env):
    reload_module_terms(env)
