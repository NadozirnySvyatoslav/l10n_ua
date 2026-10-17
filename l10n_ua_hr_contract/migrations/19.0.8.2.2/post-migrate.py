"""Fill «Full Reference» of termination reasons (#158).

`full_reference` is a stored compute that had no `@api.depends`, so it was
never computed and every reason — the shipped ones included — showed an
empty reference. Adding the dependency does not recompute existing rows, so
this does it once.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    reasons = env['hr.termination.reason'].with_context(
        active_test=False).search([])
    env.add_to_compute(reasons._fields['full_reference'], reasons)
    reasons.flush_recordset(['full_reference'])
