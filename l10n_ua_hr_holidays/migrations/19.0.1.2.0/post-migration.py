"""Leave types created by the company's "Import UA Leave Types" button get
their own category.

The button used to file the additional leave of workers with children and the
Chornobyl and war veteran leaves under the generic "Social Leave", and the
three additional leaves for working conditions under the generic "Annual
Additional Leave". The unused vacation paid out on dismissal is chosen by
category, so those types were either left out of it or counted by the wrong
rule.

Only the types the button created are moved: same company-bound name as the
button gives and the category it set. A type renamed or recategorised by hand
is left alone.
"""

import logging

_logger = logging.getLogger(__name__)

# Name the button gives, the category it used to set, the right category.
# The names are data the button writes, matched as stored.
RECATEGORISED = (
    ('Соціальна відпустка (на дітей)', 'social', 'social_children'),
    ('Додаткова чорнобильцям', 'social', 'chornobyl'),
    ('Додаткова ветеранам війни', 'social', 'veteran'),
    ('Додаткова за шкідливі умови праці', 'annual_additional', 'annual_hazardous'),
    ('Додаткова за ненормований робочий день', 'annual_additional', 'annual_irregular'),
    ('Додаткова за особливий характер праці', 'annual_additional', 'annual_special'),
)


def migrate(cr, version):
    if not version:
        return
    for name, old_category, new_category in RECATEGORISED:
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
            _logger.info(
                'Leave types %s: category %s -> %s', ids, old_category, new_category)
