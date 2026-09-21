"""Every company keeps its own PSP parameters; no record is shared.

The pre-migration has split shared records and the data file has created
the statutory periods for every company without parameters. What is left:

- the seeded records bound to a company lose their xmlids: they are now that
  company's own records like any other. The statutory values now live in the
  company-less reference `hr.psp.parameters.template`, and no company's
  records are tied to the module data;
- the record rule, under noupdate, still lets records without a company
  through;
- open payslips (draft / verify) get PSP and taxes recomputed, since the
  parameters they are computed on may have changed. Done payslips are paid
  documents and stay as they are.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OLD_RULE_DOMAIN = "['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]"
PAYSLIP_RECOMPUTED_FIELDS = (
    'psp_eligible', 'psp_amount', 'pdfo_amount', 'military_tax_amount',
    'esv_base', 'esv_amount', 'net_salary',
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Only the domain shipped by the module is replaced: a rule customised
    # by the administrator is theirs to adapt.
    rule = env.ref('l10n_ua_hr_salary.hr_psp_parameters_company_rule',
                   raise_if_not_found=False)
    if rule and rule.domain_force == OLD_RULE_DOMAIN:
        rule.domain_force = "[('company_id', 'in', company_ids)]"

    xmlids = env['ir.model.data'].search([
        ('module', '=', 'l10n_ua_hr_salary'),
        ('model', '=', 'hr.psp.parameters'),
    ])
    xmlids.unlink()

    Payslip = env['hr.payslip']
    open_slips = Payslip.search([('state', 'in', ('draft', 'verify'))])
    for fname in PAYSLIP_RECOMPUTED_FIELDS:
        env.add_to_compute(Payslip._fields[fname], open_slips)
    env.flush_all()
    _logger.info(
        'l10n_ua_hr_salary 19.0.1.4.5: %s PSP parameter xmlids removed, PSP '
        'and taxes recomputed in %s open payslips', len(xmlids), len(open_slips))
