from odoo import fields, models


class L10nUaAgreement(models.Model):
    _name = 'l10n_ua.agreement'
    _inherit = ['l10n_ua.agreement', 'l10n_ua.edo.mixin']

    def _edo_reports(self):
        """The agreement itself first, then its other forms (the act)."""
        reports = super()._edo_reports()
        main = self.env.ref('l10n_ua_agreement.action_report_agreement', raise_if_not_found=False)
        return reports.sorted(lambda r: r != main)

    def _edo_meta(self):
        meta = super()._edo_meta()
        meta.update({
            'title': f'Договір № {self.code} — {self.name}' if self.code else self.name,
            'number': self.code or False,
            'date': self.signature_date or self.start_date,
            'amount': self.amount_total,
            'currency': self.currency_id.name,
        })
        return meta

    def _edo_on_state(self, edo_document):
        super()._edo_on_state(edo_document)
        if edo_document.state in ('sent', 'signing', 'signed_owner') and self.state == 'draft':
            self.state = 'to_sign'
        elif edo_document.state == 'signed' and self.state in ('draft', 'to_sign'):
            vals = {
                'state': 'signed',
                'signature_date': self.signature_date or fields.Date.context_today(self),
            }
            archive = edo_document.archive_attachment_id
            if archive and not self.signed_document:
                vals.update({'signed_document': archive.datas, 'signed_filename': archive.name})
            self.write(vals)
