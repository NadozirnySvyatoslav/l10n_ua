"""Leave types get their own category, and draft dismissal orders their day
count by the new rule.

1. Leave types. The company's "Import UA Leave Types" button used to file
   the additional leave of workers with children and the Chornobyl and war
   veteran leaves under the generic "Social Leave", and the three additional
   leaves for working conditions under the generic "Annual Additional Leave".
   The module's own shared leave types carried the same categories until
   January 2026, and their data file is never reloaded (noupdate), so
   databases installed before then still have them. The unused vacation paid
   out on dismissal is chosen by category, so those types were either left
   out of it or counted by the wrong rule.

   Only records still holding the old category are moved: the shared types
   are found by their external id, the button's types by the company-bound
   name the button gives. A type renamed or recategorised by hand is left
   alone, and running the script again changes nothing.

2. Draft dismissal orders. The day count of the unused vacation is stored on
   the order and recomputed only when the employee or the dismissal date
   changes, so a draft written before this update keeps the figure of the
   old rule. A draft still holding the old rule's figure (the remaining days
   of the employee's balances of the dismissal year) gets it recounted; a
   figure typed in by hand is kept. Either way the history says what the new
   rule gives. Confirmed orders are left as issued.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Name the button gives, the category it used to set, the right category.
# The names are data the button writes, matched as stored.
BUTTON_TYPES = (
    ('Соціальна відпустка (на дітей)', 'social', 'social_children'),
    ('Додаткова чорнобильцям', 'social', 'chornobyl'),
    ('Додаткова ветеранам війни', 'social', 'veteran'),
    ('Додаткова за шкідливі умови праці', 'annual_additional', 'annual_hazardous'),
    ('Додаткова за ненормований робочий день', 'annual_additional', 'annual_irregular'),
    ('Додаткова за особливий характер праці', 'annual_additional', 'annual_special'),
)

# External id of the module's shared type, its old category, the right one.
SHARED_TYPES = (
    ('leave_type_social_children', 'social', 'social_children'),
    ('leave_type_chornobyl', 'social', 'chornobyl'),
    ('leave_type_veteran', 'social', 'veteran'),
    ('leave_type_additional_hazard', 'annual_additional', 'annual_hazardous'),
    ('leave_type_additional_irregular', 'annual_additional', 'annual_irregular'),
    ('leave_type_additional_special_work', 'annual_additional', 'annual_special'),
)


def _recategorise(cr):
    for xmlid, old_category, new_category in SHARED_TYPES:
        cr.execute("""
            UPDATE hr_leave_type t
               SET ua_leave_category = %s
              FROM ir_model_data d
             WHERE d.module = 'l10n_ua_hr_holidays'
               AND d.model = 'hr.leave.type'
               AND d.name = %s
               AND d.res_id = t.id
               AND t.ua_leave_category = %s
         RETURNING t.id
        """, (new_category, xmlid, old_category))
        ids = [row[0] for row in cr.fetchall()]
        if ids:
            _logger.info('Shared leave type %s %s: category %s -> %s',
                         xmlid, ids, old_category, new_category)
    for name, old_category, new_category in BUTTON_TYPES:
        # The name is translatable (jsonb): match it in any language it was
        # stored in.
        cr.execute("""
            UPDATE hr_leave_type
               SET ua_leave_category = %s
             WHERE company_id IS NOT NULL
               AND ua_leave_category = %s
               AND %s IN (SELECT value FROM jsonb_each_text(name))
         RETURNING id
        """, (new_category, old_category, name))
        ids = [row[0] for row in cr.fetchall()]
        if ids:
            _logger.info('Leave types %s: category %s -> %s', ids, old_category, new_category)


def _recount_draft_dismissals(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = env['res.lang'].get_installed()
    env = api.Environment(cr, SUPERUSER_ID, {
        'lang': env.user.lang or (installed[0][0] if installed else 'en_US'),
    })
    orders = env['hr.order'].search([
        ('order_type', '=', 'dismissal'),
        ('state', '=', 'draft'),
    ])
    for order in orders:
        old = order.unused_vacation_days
        ref_date = order.date_dismissal or order.date
        # The old rule: the remaining days of the employee's balances of the
        # dismissal year, never below zero. Read before anything recomputes
        # the balances.
        cr.execute("""
            SELECT COALESCE(SUM(remaining_days), 0)
              FROM hr_vacation_balance
             WHERE employee_id = %s AND year = %s
        """, (order.employee_id.id, ref_date.year if ref_date else 0))
        old_rule = max(0.0, cr.fetchone()[0] or 0.0)
        computed = round(old, 2) == round(old_rule, 2)
        order._compute_unused_vacation_days()
        new = order.unused_vacation_days
        if not computed:
            # Typed in by hand: keep it, say what the new rule gives.
            order.unused_vacation_days = old
            order.message_post(body=env._(
                'The days of unused vacation to compensate were entered by '
                'hand and are kept: %(old)s. By the new rule they are '
                '%(new)s; check the figure.',
                old='%.2f' % old, new='%.2f' % new))
            _logger.info('Dismissal order %s: hand-entered %.2f kept (new rule %.2f)',
                         order.id, old, new)
            continue
        if round(old, 2) == round(new, 2):
            continue
        order.message_post(body=env._(
            'The days of unused vacation to compensate were recounted by the '
            'new rule: %(old)s → %(new)s. If the order text was already '
            'loaded from a template, load the template again.',
            old='%.2f' % old, new='%.2f' % new))
        _logger.info('Dismissal order %s: unused vacation days %.2f -> %.2f',
                     order.id, old, new)

def migrate(cr, version):
    if not version:
        return
    _recategorise(cr)
    _recount_draft_dismissals(cr)
