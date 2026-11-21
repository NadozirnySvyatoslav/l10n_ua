{
    'name': 'Ukraine - Clickbot CI',
    'version': '20.0.1.0.0',
    'category': 'Hidden/Tests',
    'summary': 'CI only: run the Odoo clickbot over the apps with l10n_ua menus',
    'description': """
Test-only addon used by .github/workflows/clickbot.yml (issue #635).

Installing it installs every repository module that adds menus (the
``depends`` list below is the single source of that list); its test
``click_l10n_ua`` opens every menu, view, filter, first record and "New"
form of each app that contains such menus, as admin and as demo.

Not meant for production databases.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    # Repository modules that add menus. Left out: l10n_ua_agreement (needs
    # the OCA agreement/contract/sign_oca addons, absent from 20.0) and
    # telegram_bot_m2o (still a 19.0 module, not installable on 20.0).
    'depends': [
        'l10n_ua_account_base',
        'l10n_ua_account_vat',
        'l10n_ua_accounting',
        'l10n_ua_assets',
        'l10n_ua_bank_currency_sync',
        'l10n_ua_bank_payment',
        'l10n_ua_bank_sync',
        'l10n_ua_budget_base',
        'l10n_ua_budget_estimate',
        'l10n_ua_budget_kpkvk_import',
        'l10n_ua_budget_reports',
        'l10n_ua_budget_treasury',
        'l10n_ua_delivery_base',
        'l10n_ua_education_base',
        'l10n_ua_education_edebo',
        'l10n_ua_education_meals',
        'l10n_ua_education_scholarship',
        'l10n_ua_fop',
        'l10n_ua_hr_attendance_sheet',
        'l10n_ua_hr_base',
        'l10n_ua_hr_business_trip',
        'l10n_ua_hr_contract',
        'l10n_ua_hr_documents',
        'l10n_ua_hr_documents_certificates',
        'l10n_ua_hr_fss',
        'l10n_ua_hr_holidays',
        'l10n_ua_hr_reports',
        'l10n_ua_hr_salary',
        'l10n_ua_hr_salary_account',
        'l10n_ua_hr_salary_bonus',
        'l10n_ua_hr_vacation_reserve',
        'l10n_ua_marketplace_base',
        'l10n_ua_medecin_base',
        'l10n_ua_medecin_clinical',
        'l10n_ua_medecin_ehealth',
        'l10n_ua_medecin_nszu',
        'l10n_ua_medecin_patient',
        'l10n_ua_prro_base',
        'l10n_ua_prro_checkbox',
        'l10n_ua_stock_forms',
        'l10n_ua_supplier_prices_base',
        'l10n_ua_tax',
        'l10n_ua_tax_4df',
        'l10n_ua_tax_cabinet',
    ],
    'data': [],
    'installable': True,
    'auto_install': False,
    'application': False,
}
