{
    'name': 'Ukraine - Stock Reports',
    'version': '20.0.1.1.0',
    'category': 'Inventory/Localization',
    'summary': 'Ukrainian warehouse forms: the material report',
    'description': """
Ukraine - Stock Reports
=======================

Ukrainian warehouse paperwork on top of the standard Inventory app, without
pulling in the accounting localization.

* Material report — opening balance, receipts, issues and closing balance
  per product and storage place of one store, for a period,
  shown as a list with product-category and storage-place search panels or
  as a pivot table, and printable as the paper form.

The order that approved the form (Minstat No 193 of 21.06.1996) has been
repealed, but the obligation to account for materials held by a person in
charge has not, so the form is still what Ukrainian accountants ask for.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'stock',
    ],
    'data': [
        'security/ir.access.csv',
        'security/material_report_security.xml',
        'report/material_report.xml',
        # The screen first, then the dialog it opens: the period form is
        # referenced by name from the wizard, not by the views above.
        'views/material_report_views.xml',
        'wizard/material_report_wizard_views.xml',
    ],
    # Odoo keeps the pivot table in a separate bundle (web/static/src/views/
    # pivot/** lives in web.assets_backend_lazy), so the report views are split
    # across two bundles: in the ordinary one the import of @web/views/pivot/*
    # does not resolve. The shared period component stays in assets_backend,
    # where both can see it.
    'assets': {
        'web.assets_backend': [
            'l10n_ua_stock_forms/static/src/material_report/search_model.js',
            'l10n_ua_stock_forms/static/src/material_report/period_range.js',
            'l10n_ua_stock_forms/static/src/material_report/period_range.xml',
            'l10n_ua_stock_forms/static/src/material_report/period_range.scss',
            'l10n_ua_stock_forms/static/src/material_report/list_view.js',
            'l10n_ua_stock_forms/static/src/material_report/list_view.xml',
            'l10n_ua_stock_forms/static/src/material_report/list_view.scss',
            'l10n_ua_stock_forms/static/src/material_report/print_menu.js',
            'l10n_ua_stock_forms/static/src/material_report/print_menu.xml',
        ],
        # The tour bundle: loaded only when tests run.
        'web.assets_tests': [
            'l10n_ua_stock_forms/static/tests/tours/*.js',
        ],
        'web.assets_backend_lazy': [
            'l10n_ua_stock_forms/static/src/material_report/pivot_view.js',
            'l10n_ua_stock_forms/static/src/material_report/pivot_view.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
