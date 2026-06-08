{
    'name': 'Ukraine - 4DF Unified Tax Report',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': '4ДФ — об\'єднана квартальна звітність ПДФО/ВЗ/ЄСВ '
               '(заміна 1ДФ + Д5 з 01.01.2021)',
    'description': """
Ukraine 4DF Unified Tax Report (J0501T01 / F0501T01)
=====================================================

Quarterly combined report on PDFO / Military Tax / ESV. Replaced
1DF and D5 from 2021-01-01.

* Header model + Appendix 4ДФ (per-person PDFO/Military)
* Appendix 1 (ESV summary per person)
* Aggregation from hr.payslip
* XML export (basic structure; full XSD validation — separate task)

Regulatory base: Наказ Мінфіну № 4 від 13.01.2015 зі змінами,
форма J0501T01 (юрособа) / F0501T01 (ФОП).

This is an ACCOUNTING/TAX report, not an HR operational tool. It
aggregates payroll data calculated by l10n_ua_hr_salary and produces
a filing for submission through M.E.Doc / FREDO / Tax Cabinet.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_account_base',
        'l10n_ua_hr_salary',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/l10n_ua_tax_4df_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
