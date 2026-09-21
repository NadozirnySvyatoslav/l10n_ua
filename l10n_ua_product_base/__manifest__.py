{
    'name': 'Ukraine - Product Codes',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Localization',
    'summary': 'UKTZED and DKPP codes on products, shared by the UA modules',
    'description': """
Ukraine - Product Codes
=======================

The two statutory classifier codes a Ukrainian product carries, in one place:

* **UKTZED** (УКТ ЗЕД) — the goods nomenclature of the customs tariff. Box 3.1
  of a tax invoice, mandatory for goods.
* **DKPP** (ДКПП, ДК 016:2010) — the classifier of products and services. Box
  3.3 of a tax invoice, mandatory for services.

The codes belong to the product, not to any one document, and the same value is
read by the tax invoice (`l10n_ua_account_vat`), the PRRO receipt
(`l10n_ua_prro_base`) and the marketplace feeds (`l10n_ua_marketplace_base`).
Keeping them here lets a marketplace-only installation have them without
pulling in the accounting localization.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'product',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
