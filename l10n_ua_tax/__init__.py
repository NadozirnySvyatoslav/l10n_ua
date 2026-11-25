from . import models


def post_init_hook(env):
    # План рахунків міг бути завантажений до встановлення модуля (#560).
    env['account.tax']._l10n_ua_fill_vat_kind()
