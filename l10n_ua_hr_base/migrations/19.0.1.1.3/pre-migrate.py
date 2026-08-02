"""Merge the Ukrainian bank_account_id into the core bank_account_ids.

`hr.employee.bank_account_id` (Many2one) duplicated the native
`hr.employee.bank_account_ids` (Many2many, relation employee_bank_account_rel).
Both point at res.partner.bank, so nothing about the stored account changes —
only the link from the employee moves onto the native field.

The script runs before the ORM drops the field, while the legacy column is
still readable. Every step is probed and idempotent, and no row is discarded:
the copy uses ON CONFLICT DO NOTHING so re-running is harmless.

One case deserves the HR officer's attention and is therefore logged instead
of being silently fixed: the legacy field had no domain, so it could point at
an account belonging to some other partner. The native field is rendered with
a domain restricted to the employee's own work contact, so such an account
still exists and is still linked, but it will not show up in the widget until
its partner is corrected. Those employees are listed below by name.
"""

import logging

from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

_PREFIX = "l10n_ua_hr_base 19.0.1.1.3:"


def migrate(cr, version):
    if not column_exists(cr, 'hr_employee', 'bank_account_id'):
        _logger.info("%s no legacy bank_account_id column, nothing to merge.", _PREFIX)
        return
    if not table_exists(cr, 'employee_bank_account_rel'):
        # The native Many2many belongs to hr, which is a dependency, so this
        # should not happen — but dropping the column without a place to put
        # the data would lose it.
        _logger.warning(
            "%s employee_bank_account_rel is missing, leaving bank_account_id "
            "untouched so no account link is lost.", _PREFIX)
        return

    cr.execute("SELECT count(*) FROM hr_employee WHERE bank_account_id IS NOT NULL")
    to_migrate = cr.fetchone()[0]
    if not to_migrate:
        _logger.info("%s no employee carries a legacy bank account.", _PREFIX)

    # Accounts whose partner is not the employee's work contact: they survive
    # the merge but stay invisible in the native widget until reassigned.
    cr.execute("""
        SELECT e.id, e.name, b.acc_number
          FROM hr_employee e
          JOIN res_partner_bank b ON b.id = e.bank_account_id
         WHERE e.bank_account_id IS NOT NULL
           AND (e.work_contact_id IS NULL OR b.partner_id != e.work_contact_id)
         ORDER BY e.id
    """)
    mismatched = cr.fetchall()
    if mismatched:
        _logger.warning(
            "%s %s employee(s) keep a bank account that belongs to another "
            "partner. The link is preserved, but the account stays hidden in "
            "the employee form until its partner is set to the employee's work "
            "contact: %s", _PREFIX, len(mismatched),
            ', '.join('%s (id=%s, acc=%s)' % (name, eid, acc or '')
                      for eid, name, acc in mismatched))

    cr.execute("""
        INSERT INTO employee_bank_account_rel (employee_id, bank_account_id)
        SELECT id, bank_account_id
          FROM hr_employee
         WHERE bank_account_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    _logger.info(
        "%s %s of %s legacy bank account link(s) copied onto bank_account_ids "
        "(the rest were already linked).", _PREFIX, cr.rowcount, to_migrate)

    # Odoo never drops the column of a removed field on its own.
    cr.execute("ALTER TABLE hr_employee DROP COLUMN IF EXISTS bank_account_id")
    _logger.info("%s legacy bank_account_id column dropped.", _PREFIX)
