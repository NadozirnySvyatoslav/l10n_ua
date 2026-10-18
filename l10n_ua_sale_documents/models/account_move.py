from odoo import models

ACT_REPORT = 'l10n_ua_doc_reports.action_report_act'
VYDATKOVA_REPORT = 'l10n_ua_doc_reports.action_report_vydatkova'


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _l10n_ua_get_primary_doc_reports(self):
        """Primary documents (акт / видаткова накладна) to send with the customer invoice.

        The choice comes from the invoice company; with «auto» it follows the invoice lines:
        only services → акт, only goods → видаткова накладна, both → both documents.
        Down payment (prepayment) invoices get no primary document.

        :return: `ir.actions.report` recordset, empty when nothing has to be attached
        """
        self.ensure_one()
        reports = self.env['ir.actions.report']
        if self.move_type != 'out_invoice':
            return reports
        lines = self._get_ua_report_lines()
        if 'is_downpayment' in lines._fields:
            # A prepayment invoice delivers nothing yet: no act / delivery note for it
            lines = lines.filtered(lambda l: not l.is_downpayment)
        if not lines:
            return reports
        mode = self.company_id.l10n_ua_invoice_primary_doc
        xmlids = []
        if mode == 'act':
            xmlids = [ACT_REPORT]
        elif mode == 'vydatkova':
            xmlids = [VYDATKOVA_REPORT]
        elif mode == 'auto':
            types = set(lines.product_id.mapped('type'))
            if 'service' in types or 'consu' not in types:
                xmlids.append(ACT_REPORT)
            if 'consu' in types:
                xmlids.append(VYDATKOVA_REPORT)
        for xmlid in xmlids:
            reports |= self.env.ref(xmlid, raise_if_not_found=False) or reports
        return reports

    def _l10n_ua_get_primary_doc_filename(self, report):
        """'Акт_INV_2026_00001.pdf': the report print name, made safe for a file name."""
        self.ensure_one()
        name = self.env['ir.actions.report']._l10n_ua_eval_report_name(report, self)
        return '%s.pdf' % name.replace('/', '_')
