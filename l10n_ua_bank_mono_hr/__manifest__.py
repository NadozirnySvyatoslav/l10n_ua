{
    'name': 'Ukraine - monobank Payroll (Corporate API)',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Salary registries, salary contacts and payslips in the monobank app',
    'description': """
Payroll through the monobank Corporate API
==========================================

* Salary registry sent to monobank instead of a client-bank file: the
  "monobank API" format of the payroll bank export creates a registry that
  goes in batches of up to 1000 recipients and is then finalized; the
  status is polled by a scheduled action and the decline reason is posted
  in the chatter.
* Salary contacts: employees (RNOKPP or document, IBAN) are matched with
  the salary contacts of the company in monobank, missing ones created,
  mismatches reported.
* Payslips in the monobank app: accruals and deductions of the payslips are
  uploaded per period, then published to the employees; employees monobank
  does not know are listed, and the PDF of a payslip can be downloaded.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_mono',
        'l10n_ua_hr_salary',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/mono_salary_registry_views.xml',
        'views/mono_payslip_import_views.xml',
        'views/hr_payslip_run_views.xml',
        'wizard/hr_payslip_bank_export_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'price': 0,
    'currency': 'EUR',
}
