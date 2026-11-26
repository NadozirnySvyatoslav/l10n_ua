"""20.0.2.0.0: запобіжник перед переходом з OCA `agreement` (1.x) на 2.0.

У 20.0 версія 1.x будувалась на OCA `agreement`; 2.0 має власну модель
`l10n_ua.agreement`, а переносу договорів з OCA у 20.0 ще немає (рішення №7,
26.11.2026). Щоб договори не загубились мовчки, оновлення 1.x -> 2.0
зупиняється, якщо в базі встановлено OCA `agreement` і в ньому є записи.

Чиста база або база без договорів OCA — нічого не робимо. База, що вже прийшла
з 19.0.2.0.0 (договори перенесено там), — теж нічого: перевіряємо лише 1.x.
OCA-модулі автоматично не видаляємо.
"""

from odoo.exceptions import UserError
from odoo.tools.sql import table_exists


def _module_major(version):
    """'20.0.1.1.0' -> 1, '19.0.2.0.0' -> 2, '1.1.0' -> 1."""
    parts = version.split('.')
    try:
        return int(parts[2] if len(parts) == 5 else parts[0])
    except (IndexError, ValueError):
        return 0


def check_oca_agreements(cr, version):
    if not version or _module_major(version) >= 2:
        return
    cr.execute("""
        SELECT 1 FROM ir_module_module
         WHERE name = 'agreement' AND state IN ('installed', 'to upgrade')
    """)
    if not cr.fetchone() or not table_exists(cr, 'agreement'):
        return
    cr.execute("SELECT count(*) FROM agreement")
    count = cr.fetchone()[0]
    if count:
        raise UserError(
            f"l10n_ua_agreement {version} -> 2.0: договорів OCA у базі (таблиця "
            f"agreement): {count}. Автоматичного переносу в l10n_ua.agreement "
            f"для 20.0 немає, оновлення зупинено, щоб договори не загубились. "
            f"Для переносу зверніться до розробника (Many2one)."
        )


def migrate(cr, version):
    check_oca_agreements(cr, version)
