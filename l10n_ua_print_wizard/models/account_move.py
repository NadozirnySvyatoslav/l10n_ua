from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_print_pdf(self):
        """Ask which report to print instead of printing the default one."""
        self.ensure_one()
        wizard = self.env['l10n_ua.print.wizard'].create({'move_ids': [(6, 0, self.ids)]})
        if len(wizard.available_report_ids) <= 1:
            return wizard.action_print()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Print"),
            'res_model': 'l10n_ua.print.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }
