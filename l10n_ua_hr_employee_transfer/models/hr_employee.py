from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    previous_employee_id = fields.Many2one(
        'hr.employee',
        string='Попередній запис (переведення)',
        check_company=False,
        copy=False,
        help='Запис співробітника в попередній компанії (створений через Transfer Wizard).',
    )
    next_employee_id = fields.Many2one(
        'hr.employee',
        string='Наступний запис (переведення)',
        check_company=False,
        copy=False,
        help='Запис співробітника в цільовій компанії (створений через Transfer Wizard).',
    )

    def action_open_transfer_wizard(self):
        self.ensure_one()
        return {
            'name': 'Переведення в іншу організацію',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_employee_id': self.id,
                'default_source_company_id': self.company_id.id,
            },
        }
