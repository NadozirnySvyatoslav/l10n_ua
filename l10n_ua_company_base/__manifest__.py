{
    'name': 'Ukraine - Company Registration Data',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'EDRPOU, KATOTTG, tax office and other statutory company details',
    'description': """
Ukraine - Company Registration Data
===================================

The registration details a Ukrainian company is identified by, on `res.company`:

* **EDRPOU** — the state register code, quoted on every document and in every
  report filed with a state body.
* **KOATUU** and **KATOTTG** — the administrative-territorial codes; KATOTTG
  is required by the unified PIT/military-levy/USC report.
* **Tax office code** (ДПІ) and **Pension fund office code** (ПФУ) — where the
  company files.
* **Main KVED**, **ownership form**, **legal address**.

None of this is HR data, accounting data or tax data in particular — it is who
the company *is*, and the payroll reports, the tax cabinet, the bank exports
and the printed forms all need it. Keeping it in a module that depends on
nothing but `base` means a tax or accounting installation can read it without
pulling in the HR block, and an HR installation without pulling in accounting.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'base',
    ],
    'data': [
        'views/res_company_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
