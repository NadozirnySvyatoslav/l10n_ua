"""Договір у взаємозаліку (#371).

Договір на проводці (`account.move.l10n_ua_agreement_id`) один на весь документ, а
рядок проводки успадковує його через related-поле. Тож залік між різними
договорами однією проводкою в розрізі договорів не розкладеш: договір
проставляється на проводку заліку, лише коли він однозначний — вказаний у
документі або спільний для всіх обраних рахунків.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class L10nUaDebtNetting(models.Model):
    _inherit = 'l10n_ua.debt.netting'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        tracking=True,
        domain="[('commercial_partner_id', '=', commercial_partner_id)]",
        help='Limit the netting to the documents of one agreement. The '
             'agreement is set on the netting entry, so it shows in the trial '
             'balance and the reconciliation act by agreement.',
    )

    def _get_candidate_domain(self):
        domain = super()._get_candidate_domain()
        if self.l10n_ua_agreement_id:
            domain.append(('l10n_ua_agreement_id', '=', self.l10n_ua_agreement_id.id))
        return domain

    def _get_move_agreement(self):
        """Договір для проводки заліку: явний або єдиний серед документів."""
        self.ensure_one()
        if self.l10n_ua_agreement_id:
            return self.l10n_ua_agreement_id
        lines = self.line_ids.filtered(
            lambda l: not self.currency_id.is_zero(l.amount_offset))
        agreements = lines.move_line_id.l10n_ua_agreement_id
        if len(agreements) == 1 and all(ml.l10n_ua_agreement_id for ml in lines.move_line_id):
            return agreements
        return self.env['l10n_ua.agreement']

    @api.constrains('l10n_ua_agreement_id')
    def _check_lines_agreement(self):
        self.line_ids._check_agreement()

    def _prepare_move_vals(self, prepared):
        vals = super()._prepare_move_vals(prepared)
        agreement = self._get_move_agreement()
        if agreement:
            vals['l10n_ua_agreement_id'] = agreement.id
        return vals


class L10nUaDebtNettingLine(models.Model):
    _inherit = 'l10n_ua.debt.netting.line'

    l10n_ua_agreement_id = fields.Many2one(
        related='move_line_id.l10n_ua_agreement_id', string='Agreement')

    @api.constrains('move_line_id')
    def _check_agreement(self):
        for line in self:
            agreement = line.netting_id.l10n_ua_agreement_id
            if agreement and line.move_line_id.l10n_ua_agreement_id != agreement:
                raise ValidationError(_(
                    'Document %(document)s does not belong to agreement %(agreement)s.',
                    document=line.move_id.display_name,
                    agreement=agreement.display_name))
