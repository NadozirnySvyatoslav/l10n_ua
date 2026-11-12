"""Підстави звільнення (#505): згода профспілки і вихідна допомога.

Записи довідника завантажено з noupdate, тож оновлення модуля їх не міняє.
Тут виправляємо лише поставлені модулем записи (за xmlid) і лише поля, які
модуль досі лишав порожніми або заповнював не за КЗпП:

* ст. 43 — попередня згода профспілки для пп. 1 (крім ліквідації), 2–5, 7
  ст. 40 і пп. 2, 3 ст. 41;
* ст. 44 — при призові (п. 3 ст. 36) дві мінімальні заробітні плати, а не
  два середні заробітки; за п. 5 ст. 40 вихідна допомога не передбачена.
"""
from odoo import SUPERUSER_ID, api

CONSENT = ('reorganization', 'reduction', 'incompetence', 'systematic', 'absence',
           'long_absence', 'intoxication', 'trust', 'immoral')
NO_CONSENT = ('liquidation',)


def _record(env, name):
    return env.ref('l10n_ua_hr_contract.termination_reason_%s' % name, raise_if_not_found=False)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for name in CONSENT:
        rec = _record(env, name)
        if rec and not rec.requires_union_consent:
            rec.requires_union_consent = True
    for name in NO_CONSENT:
        rec = _record(env, name)
        if rec and rec.requires_union_consent:
            rec.requires_union_consent = False
    military = _record(env, 'military')
    if military and military.compensation_amount == 'two_months':
        military.compensation_amount = 'two_min_wages'
    long_absence = _record(env, 'long_absence')
    if long_absence and long_absence.compensation_amount == 'one_month':
        long_absence.write({'requires_compensation': False, 'compensation_amount': 'none'})
