from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrPayslipBankExport(models.TransientModel):
    _inherit = 'hr.payslip.bank.export'

    file_format = fields.Selection(
        selection_add=[('mono_api', 'monobank API (salary registry)')],
        ondelete={'mono_api': 'set default'},
    )
    mono_config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='monobank Connection',
        compute='_compute_mono_config_id', store=True, readonly=False,
        domain="[('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),"
               " ('company_id', '=', company_id)]")
    mono_registry_type_id = fields.Many2one(
        'l10n_ua.mono.salary.registry.type', string='Registry Type',
        domain="[('config_id', '=', mono_config_id)]")

    @api.depends('payer_account_id', 'company_id', 'file_format')
    def _compute_mono_config_id(self):
        Config = self.env['l10n_ua.bank.sync.config']
        for wizard in self:
            if wizard.file_format != 'mono_api':
                wizard.mono_config_id = wizard.mono_config_id
                continue
            wizard.mono_config_id = Config._mono_corp_config_for_iban(
                wizard.payer_account_id.acc_number, wizard.company_id) or Config.search([
                    ('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),
                    ('company_id', '=', wizard.company_id.id)], limit=1)

    def action_mono_fetch_types(self):
        self.ensure_one()
        if not self.mono_config_id:
            raise UserError(_('Choose the monobank connection.'))
        types = self.env['l10n_ua.mono.salary.registry.type']._mono_fetch(self.mono_config_id)
        if not self.mono_registry_type_id and types:
            self.mono_registry_type_id = types[:1]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _mono_registry_lines(self, slips):
        """Registry recipients, with the checks of the file formats: one
        payment per employee to the primary account, zero amounts skipped."""
        Line = self.env['l10n_ua.mono.salary.registry.line']
        period = self._period_label()
        lines, missing = [], []
        for slip in slips:
            amount = round(slip.net_salary, 2)
            if amount <= 0:
                continue
            employee = slip.employee_id
            if not employee.primary_bank_account_id.acc_number:
                missing.append(employee.name)
                continue
            vals = Line._vals_from_employee(employee, amount, slip)
            if self.mono_registry_type_id.additional_purpose_allowed and \
                    '{employee}' in (self.payment_purpose or ''):
                # Only a per-employee purpose differs between recipients.
                vals['additional_purpose'] = ' ' + (self.payment_purpose or '').format(
                    period=period, employee=employee.name or '',
                    rnokpp=employee.rnokpp or '')
            lines.append(vals)
        if missing:
            raise UserError(_(
                'No bank account (IBAN) for employees:\n- %s'
            ) % '\n- '.join(missing))
        if not lines:
            raise UserError(_(
                'Немає рядків для виплати (усі суми нульові або немає '
                'закритих листків за період).'))
        return lines

    def action_generate(self):
        if self.file_format != 'mono_api':
            return super().action_generate()
        self.ensure_one()
        if not self.mono_config_id:
            raise UserError(_('Choose the monobank corporate API connection.'))
        if not self.mono_registry_type_id:
            raise UserError(_('Choose the registry type (fetch the list from monobank).'))
        slips = self._get_payslips()
        if not slips:
            raise UserError(_('Немає закритих (Done) листків за вибором.'))
        lines = self._mono_registry_lines(slips)
        date_from = self.date_from or self.payslip_run_id.date_start
        date_to = self.date_to or self.payslip_run_id.date_end
        name = (self.payment_purpose or '').format(
            period=self._period_label(), employee='', rnokpp='').strip() \
            or _('Salary %s', self._period_label())
        registry = self.env['l10n_ua.mono.salary.registry'].create({
            'name': name,
            'company_id': self.company_id.id,
            'config_id': self.mono_config_id.id,
            'registry_type_id': self.mono_registry_type_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'payslip_run_id': self.payslip_run_id.id,
            'line_ids': [(0, 0, vals) for vals in lines],
        })
        # Created as a draft to look through, then sent with its button.
        return {
            'type': 'ir.actions.act_window',
            'res_model': registry._name,
            'res_id': registry.id,
            'view_mode': 'form',
            'target': 'current',
        }
