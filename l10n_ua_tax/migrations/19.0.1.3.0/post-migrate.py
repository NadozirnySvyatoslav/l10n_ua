from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """#560: вид ставки ПДВ стоковим податкам уже наявних компаній.

    Заповнюються лише порожні значення, ручні правки лишаються.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.tax']._l10n_ua_fill_vat_kind()
