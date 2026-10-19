"""Рядки декларації з ПДВ — за формою наказу № 400 (J0200126).

Раніше 1.2/10.2/11.2 означали ставку 14 %, а 1.3/10.3/11.3 — 7 %; у формі
навпаки (1.2 — 7 %, 1.3 — 14 %). Міняємо збережені значення місцями. Колишній
рядок 6 («не є об'єктом») у формі входить до рядка 5.
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns "
               "WHERE table_name = 'l10n_ua_vat_declaration' AND column_name = 'line_1_3_vat'")
    if not cr.fetchone():
        return
    swaps = []
    for row in ('1', '10', '11'):
        for part in ('base', 'vat'):
            a, b = f'line_{row}_2_{part}', f'line_{row}_3_{part}'
            swaps += [f'{a} = {b}', f'{b} = {a}']
    cr.execute('UPDATE l10n_ua_vat_declaration SET ' + ', '.join(swaps))
    cr.execute("SELECT 1 FROM information_schema.columns "
               "WHERE table_name = 'l10n_ua_vat_declaration' AND column_name = 'line_6_base'")
    if cr.fetchone():
        cr.execute('UPDATE l10n_ua_vat_declaration '
                   'SET line_5_base = COALESCE(line_5_base, 0) + COALESCE(line_6_base, 0)')
