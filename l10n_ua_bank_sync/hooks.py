"""Install-time fixups that a data file cannot express."""

MODULE = 'l10n_ua_bank_sync'


def reload_module_terms(env):
    """Перезавантажити переклади модуля, перетираючи наявні значення.

    Підпис кореня застосунку змінився між релізами: «Банк UA» → «Банк».
    Ключ мови для `menu_ua_bank_root` у базі вже є, а імпортер зливає
    значення як `t.value || m.name` — наявне перемагає, якщо сервер
    запущено без прапорця i18n-overwrite. Тому після встановлення та після
    оновлення версії ми свідомо перечитуємо файли перекладу цього модуля з
    overwrite: єдиним джерелом правди лишається `i18n/uk_UA.po`.

    Той самий підхід, що в `l10n_ua_accounting.hooks` (див. #276); спільного
    хелпера немає навмисно — `l10n_ua_accounting` залежить від цього модуля,
    тож імпорт у зворотний бік неможливий.
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
