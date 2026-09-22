"""Clean up after the model rename (l10n_ua.m19.* -> l10n_ua.*).

Odoo renames the records themselves just fine: the old `ir.model`, its fields,
actions and views disappear when the module is updated. The tables, however,
stay behind:

    The model l10n_ua.m19.material.report.line could not be dropped
    because it did not exist in the registry.

`ir.model.unlink` drops the table through the registry, and the renamed model
is no longer in it — so the table survives the update with its rows inside.
For transient models that is also data nobody will ever clear: the vacuum walks
the models of the registry, and this one is not there any more.

The data is no loss — these are snapshots of already produced reports, which
live only until the first vacuum anyway, so the tables are simply dropped
rather than migrated.
"""

DROPPED_TABLES = (
    'l10n_ua_m19_material_report_line',
    'l10n_ua_m19_material_report_wizard',
)


def migrate(cr, version):
    if not version:
        return
    for table in DROPPED_TABLES:
        cr.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
