from odoo import api, fields, models
from odoo.exceptions import UserError


class L10nUaPrintWizard(models.TransientModel):
    _name = 'l10n_ua.print.wizard'
    _description = "Print Document"

    move_ids = fields.Many2many('account.move', required=True)
    available_report_ids = fields.Many2many(
        'ir.actions.report', compute='_compute_available_report_ids')
    report_id = fields.Many2one(
        'ir.actions.report', string="Document",
        domain="[('id', 'in', available_report_ids)]")

    @api.depends('move_ids')
    def _compute_available_report_ids(self):
        for wizard in self:
            wizard.available_report_ids = wizard._get_print_menu_reports()

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards.filtered(lambda w: not w.report_id):
            wizard.report_id = wizard._get_default_report()
        return wizards

    def _get_default_report(self):
        """The report the core "Print" button would print, if it is in the list."""
        self.ensure_one()
        reports = self.available_report_ids
        try:
            default = self.env['account.move.send']._get_default_pdf_report_id(self.move_ids[:1])
        except UserError:
            default = self.env['ir.actions.report']
        return default if default in reports else reports[:1]

    def _get_print_menu_reports(self):
        """Reports of the gear menu → Print of the invoice form, in the same order."""
        self.ensure_one()
        bindings = self.env['ir.actions.actions'].get_bindings('account.move').get('report', [])
        ids = [
            b['id'] for b in bindings
            if not b.get('binding_view_types') or 'form' in b['binding_view_types'].split(',')
        ]
        reports = self.env['ir.actions.report'].browse(ids)
        valid = set(reports.get_valid_action_reports('account.move', self.move_ids.ids))
        return reports.filtered(lambda r: r.id in valid)

    def action_print(self):
        self.ensure_one()
        report = self.report_id or self.available_report_ids[:1]
        if not report:
            raise UserError(self.env._("There is no report to print for this document."))
        action = report.report_action(self.move_ids.ids, config=False)
        action['close_on_report_download'] = True
        return self.move_ids[:1]._get_action_with_base_document_layout_configurator(action)
