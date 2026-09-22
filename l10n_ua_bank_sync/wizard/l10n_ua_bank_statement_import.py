import json

from odoo import models, fields, _
from odoo.exceptions import UserError


class L10nUaBankStatementImport(models.TransientModel):
    """Узагальнений майстер імпорту виписки з файлу (файлові провайдери).

    Не залежить від конкретного банку: делегує розбір формату провайдеру
    (`config._file_to_payload` → `_parse_transactions`). Створює завдання й
    формує native-виписку тим самим шляхом, що й онлайн-синхронізація.
    """
    _name = 'l10n_ua.bank.statement.import'
    _description = 'Bank Statement File Import'

    config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='Bank Config', required=True,
        domain="[('exchange_type', '=', 'file')]")
    statement_file = fields.Binary(string='Statement File', required=True)
    file_name = fields.Char(string='File Name')
    date_from = fields.Date(
        string='Date From', default=fields.Date.context_today)
    date_to = fields.Date(
        string='Date To', default=fields.Date.context_today)

    def action_import(self):
        self.ensure_one()
        if self.config_id.exchange_type != 'file':
            raise UserError(_('Оберіть конфігурацію з файловим обміном.'))
        import base64
        content = self.statement_file.content
        raw_data = self.config_id._file_to_payload(content, self.file_name)

        job = self.env['l10n_ua.bank.sync.job'].create({
            'config_id': self.config_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'raw_payload': json.dumps(raw_data, ensure_ascii=False),
            'payload_fetched_at': fields.Datetime.now(),
            'source_type': 'file',
            'source_ref': self.file_name or _('statement file'),
            'state': 'fetched',
        })
        job.action_process()
        statement = job.bank_statement_id
        if statement:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Bank Statement'),
                'res_model': 'account.bank.statement',
                'res_id': statement.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Statement Import'),
            'res_model': 'l10n_ua.bank.sync.job',
            'res_id': job.id,
            'view_mode': 'form',
            'target': 'current',
        }
