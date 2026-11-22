"""Параметри ПСП з даних модуля — спільні для всіх компаній.

Записи вантажились без `company_id`, тож отримували компанію за
замовчуванням — ту, під якою встановлювали модуль. Друга компанія бази
параметрів не бачила й листок падав «No payroll parameters are defined».
Дані під noupdate, тож самі записи в наявних базах не зміняться: робимо
їх спільними тут.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE hr_psp_parameters p SET company_id = NULL
          FROM ir_model_data d
         WHERE d.model = 'hr.psp.parameters' AND d.res_id = p.id
           AND d.module = 'l10n_ua_hr_salary'
    """)
