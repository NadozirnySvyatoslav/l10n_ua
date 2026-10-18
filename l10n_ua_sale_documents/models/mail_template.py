import base64

from odoo import models

from .ir_actions_report import CORE_ORDER_REPORTS, RAHUNOK_SALE_REPORT


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    def _l10n_ua_order_reports_swapped(self):
        """Reports of this sale.order template with the Odoo order PDF replaced by the
        Рахунок-фактура, or None when the template attaches no Odoo order PDF."""
        self.ensure_one()
        core = self.env['ir.actions.report']
        for xmlid in CORE_ORDER_REPORTS:
            core |= self.env.ref(xmlid, raise_if_not_found=False) or core
        rahunok = self.env.ref(RAHUNOK_SALE_REPORT, raise_if_not_found=False)
        if not rahunok or not (self.report_template_ids & core):
            return None
        reports = self.env['ir.actions.report']
        for report in self.report_template_ids:
            reports |= rahunok if report in core else report
        return reports

    def _generate_template_attachments(self, res_ids, render_fields, render_results=None):
        """Per company, attach the Рахунок-фактура to order e-mails instead of the Odoo
        quotation / order PDF.

        The templates themselves are not changed: the substitution happens while rendering, for
        the orders whose company enabled it, so other companies, uninstalling the module or
        editing the template keep the standard behaviour.
        """
        if (
            self.model != 'sale.order'
            or 'report_template_ids' not in render_fields
            or not res_ids
        ):
            return super()._generate_template_attachments(res_ids, render_fields, render_results)
        reports = self._l10n_ua_order_reports_swapped()
        if reports is None:
            return super()._generate_template_attachments(res_ids, render_fields, render_results)

        orders = self.env['sale.order'].browse(res_ids)
        swap_ids = set(orders.filtered(lambda o: o.company_id.l10n_ua_sale_rahunok_in_mail).ids)
        keep_ids = [res_id for res_id in res_ids if res_id not in swap_ids]
        swap_ids = [res_id for res_id in res_ids if res_id in swap_ids]
        if keep_ids:
            render_results = super()._generate_template_attachments(
                keep_ids, render_fields, render_results)
        if swap_ids:
            other_fields = [f for f in render_fields if f != 'report_template_ids']
            render_results = super()._generate_template_attachments(
                swap_ids, other_fields, render_results)
            ReportAction = self.env['ir.actions.report']
            for res_id in swap_ids:
                record = self.env[self.model].browse(res_id)
                values = render_results.setdefault(res_id, {})
                values['attachments'] = []
                for report in reports:
                    content, report_format = ReportAction._render(report, [res_id])
                    name = ReportAction._l10n_ua_eval_report_name(report, record)
                    extension = '.' + report_format
                    if not name.endswith(extension):
                        name += extension
                    values['attachments'].append((name, base64.b64encode(content)))
        return render_results
