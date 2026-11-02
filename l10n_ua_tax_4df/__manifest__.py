{
    'name': 'Ukraine - 4DF Unified Tax Report',
    'version': '19.0.1.2.0',
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
* Податковий розрахунок ЮО (J0500111 v11, наказ № 243): щомісячна головна
  форма з додатками Д1 (J0510111) і Д4 (J0510411) одним пакетом
  (LINKED_DOCS), подання до ДПС з КЕП-підписом у браузері

Regulatory base: Наказ Мінфіну № 4 від 13.01.2015 зі змінами,
форма J0501T01 (юрособа) / F0501T01 (ФОП).

This is an ACCOUNTING/TAX report, not an HR operational tool. It
aggregates payroll data calculated by l10n_ua_hr_salary and produces
a filing for submission through M.E.Doc / FREDO / Tax Cabinet.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_account_base',
        'l10n_ua_hr_salary',
        'l10n_ua_hr_reports',
        'l10n_ua_sign',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/l10n_ua_payroll_tax_report_security.xml',
        'views/l10n_ua_tax_4df_views.xml',
        'views/l10n_ua_payroll_tax_report_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
