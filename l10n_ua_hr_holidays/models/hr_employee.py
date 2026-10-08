from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    vacation_anchor_date = fields.Date(
        string='Vacation Work-Year Anchor',
        tracking=True,
        help='Date the annual (work-year) vacation seniority is counted from, '
             'when it differs from the hire date. Set by the inter-company '
             'transfer wizard in "Keep Work Year" mode: art. 9 §3 of the '
             'Vacation Law lets the previous employer\'s seniority continue '
             'when the compensation for unused days is transferred along with '
             'the employee. Empty — the work year runs from the hire date.')

    def _get_vacation_anchor_date(self):
        """Carried-over anchor wins over the hire date of the new contract."""
        self.ensure_one()
        return self.vacation_anchor_date or super()._get_vacation_anchor_date()

    def _l10n_ua_fallback_wage(self, on_date):
        """The salary the averages fall back on, in the company currency.

        The wage of the current version, or the salary of the staffing line
        of its position when the version carries none and the company lets
        the staffing table stand in for it, as the payslip does. Many
        companies keep the salary in the staffing table only, and the
        fallback would then give a zero average.
        """
        self.ensure_one()
        version = self.current_version_id
        if not version:
            return 0.0
        if version.wage:
            return version._l10n_ua_wage_in_company_currency(on_date)
        if (version.company_id.wage_from_staffing or 'both') not in ('fallback', 'both'):
            return 0.0
        # Read for the version's company, as the payslip reads it: the
        # staffing table is ruled by the companies in the switcher.
        line = self.env['hr.staffing.table'].with_company(
            version.company_id)._resolve(
                version.company_id, version.department_id, version.job_id,
                on_date)
        return line._salary_in_company_currency(on_date) if line else 0.0
