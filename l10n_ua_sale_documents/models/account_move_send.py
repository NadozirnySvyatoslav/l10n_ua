from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    @api.model
    def _get_default_mail_attachments_widget(self, move, mail_template, invoice_edi_format=None,
                                             extra_edis=None, pdf_report=None):
        """Add the Ukrainian primary document(s) next to the Odoo invoice PDF.

        They are added as `dynamic_report` placeholders, the mechanism core uses for the reports
        of the mail template: the user sees (and may remove) them in the Send wizard, and
        `_generate_dynamic_reports` renders them when the mail is actually sent, also for the
        automatic sending after an online payment. The invoice PDF itself (and e-invoicing) is
        left untouched.
        """
        attachments = super()._get_default_mail_attachments_widget(
            move, mail_template, invoice_edi_format=invoice_edi_format,
            extra_edis=extra_edis, pdf_report=pdf_report,
        )
        if not move:
            return attachments
        present = {a.get('dynamic_report') for a in attachments}
        for report in move._l10n_ua_get_primary_doc_reports():
            if report.report_name in present:
                continue
            filename = move._l10n_ua_get_primary_doc_filename(report)
            attachments.append({
                'id': f'placeholder_l10n_ua_{report.id}_{filename}',
                'name': filename,
                'mimetype': 'application/pdf',
                'placeholder': True,
                'dynamic_report': report.report_name,
            })
        return attachments
