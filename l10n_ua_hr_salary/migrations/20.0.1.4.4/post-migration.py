"""Параметри ПСП — за законами про Держбюджет і п. 169.4.1 ПКУ (#329).

Записи даних під noupdate, тож виправлені значення самі до наявних баз не
дійдуть:

- прожитковий мінімум на 01.01.2024 — 3028 (було 2920);
- підвищення з 01.04.2025 (8500 / 3178) не було: 2025 рік — 8000 / 3028 весь
  рік, тож квітневий запис видаляємо, а січневий продовжуємо до кінця року;
- 2026 рік — мінзарплата 8647 і прожитковий мінімум 3328 (було 9000 / 3300).

Значення міняємо лише там, де вони досі збігаються з хибними з даних модуля:
ручні правки користувача не перетираємо.

Граничний дохід для ПСП рахувався як ПМ × 1,4 × 10 — перераховуємо його в
усіх записах. ПСП і податки перераховуємо лише у незакритих листках
(draft / verify): проведені й скасовані — вже виплачені документи.
"""

import logging
from datetime import date

from odoo import SUPERUSER_ID, api
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# xmlid → {поле: (хибне значення з даних, правильне)}
VALUE_FIXES = {
    'psp_params_2024_01': {'subsistence_minimum': (2920, 3028)},
    'psp_params_2026_01': {'subsistence_minimum': (3300, 3328), 'min_wage': (9000, 8647)},
}
PAYSLIP_RECOMPUTED_FIELDS = (
    'psp_eligible', 'psp_amount', 'pdfo_amount', 'military_tax_amount',
    'esv_amount', 'net_salary',
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    def ref(name):
        return env.ref(f'l10n_ua_hr_salary.{name}', raise_if_not_found=False)

    for xmlid, changes in VALUE_FIXES.items():
        record = ref(xmlid)
        if not record:
            continue
        vals = {
            fname: new
            for fname, (old, new) in changes.items()
            if float_compare(record[fname], old, precision_digits=2) == 0
        }
        if vals:
            record.write(vals)
            _logger.info('l10n_ua_hr_salary 20.0.1.4.4: %s → %s', xmlid, vals)

    april = ref('psp_params_2025_04')
    if (april and float_compare(april.min_wage, 8500, precision_digits=2) == 0
            and float_compare(april.subsistence_minimum, 3178, precision_digits=2) == 0):
        april.unlink()
        january = ref('psp_params_2025_01')
        if january and january.date_to == date(2025, 3, 31):
            january.date_to = date(2025, 12, 31)
        _logger.info('l10n_ua_hr_salary 20.0.1.4.4: прибрано хибне підвищення з 01.04.2025')

    Params = env['hr.psp.parameters'].with_context(active_test=False)
    params = Params.search([])
    env.add_to_compute(Params._fields['income_limit'], params)

    Payslip = env['hr.payslip']
    open_slips = Payslip.search([('state', 'in', ('draft', 'verify'))])
    for fname in PAYSLIP_RECOMPUTED_FIELDS:
        env.add_to_compute(Payslip._fields[fname], open_slips)
    env.flush_all()
    _logger.info(
        'l10n_ua_hr_salary 20.0.1.4.4: ліміт ПСП перераховано в %s записах параметрів, '
        'ПСП і податки — у %s незакритих листках', len(params), len(open_slips))
