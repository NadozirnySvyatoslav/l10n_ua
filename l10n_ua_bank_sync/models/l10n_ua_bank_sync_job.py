import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaBankSyncJob(models.Model):
    _name = 'l10n_ua.bank.sync.job'
    _description = 'Bank Sync Job'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    config_id = fields.Many2one(
        'l10n_ua.bank.sync.config',
        string='Configuration',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='config_id.company_id',
        store=True,
    )
    journal_id = fields.Many2one(
        related='config_id.journal_id',
        store=True,
    )
    provider = fields.Selection(
        related='config_id.provider',
        store=True,
    )

    # Date range
    date_from = fields.Date(
        string='Date From',
        required=True,
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
    )

    # State
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('fetching', 'Fetching from Bank'),
            ('fetched', 'Fetched'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )

    # Raw payload storage
    raw_payload = fields.Text(
        string='Raw Payload (JSON)',
        help='Raw response from bank API stored as JSON',
    )
    payload_fetched_at = fields.Datetime(
        string='Payload Fetched At',
    )

    # Import source metadata (Фаза 1: виписка-при-імпорті)
    source_type = fields.Selection([
        ('file', 'File import'),
        ('api', 'API'),
        ('manual', 'Manual'),
    ], string='Source Type')
    source_ref = fields.Char(
        string='Source Reference',
        help='Назва файлу або провайдер/endpoint API.')
    bank_statement_id = fields.Many2one(
        'account.bank.statement', string='Bank Statement', readonly=True,
        ondelete='set null',
        help='Native-виписка, сформована цим завданням.')

    # Processing results
    transactions_count = fields.Integer(
        string='Transactions Found',
        readonly=True,
    )
    imported_count = fields.Integer(
        string='Imported',
        readonly=True,
    )
    updated_count = fields.Integer(
        string='Updated',
        readonly=True,
    )
    error_count = fields.Integer(
        string='Errors',
        readonly=True,
    )

    # Logs
    log_ids = fields.One2many(
        'l10n_ua.bank.sync.log',
        'job_id',
        string='Logs',
    )
    error_message = fields.Text(
        string='Error Message',
        readonly=True,
    )

    @api.depends('config_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            config_name = rec.config_id.name if rec.config_id else ''
            date_from = rec.date_from.strftime('%d.%m.%Y') if rec.date_from else ''
            date_to = rec.date_to.strftime('%d.%m.%Y') if rec.date_to else ''
            rec.name = f"{config_name}: {date_from} - {date_to}"

    @api.onchange('config_id')
    def _onchange_config_id(self):
        """Pre-fill dates based on last completed job for selected config."""
        if not self.config_id:
            return

        # Find last completed job for this config
        last_job = self.env['l10n_ua.bank.sync.job'].search([
            ('config_id', '=', self.config_id.id),
            ('state', '=', 'done'),
        ], limit=1, order='date_to desc')

        if last_job:
            # Set date_from to last job's date_to + 1 day
            self.date_from = last_job.date_to + timedelta(days=1)
            self.date_to = fields.Date.today()
        else:
            # No previous job - default to last 7 days
            self.date_from = fields.Date.today() - timedelta(days=7)
            self.date_to = fields.Date.today()

    def _log(self, message, level='info', data=None):
        """Add log entry."""
        self.ensure_one()

        # Log to Python logger
        log_method = getattr(_logger, level, _logger.info)
        log_method(f"[Job {self.id}] {message}")

        # Create log record
        self.env['l10n_ua.bank.sync.log'].create({
            'job_id': self.id,
            'level': level,
            'message': message,
            'data': json.dumps(data, ensure_ascii=False, default=str) if data else False,
        })

    def action_fetch(self):
        """Fetch data from bank API."""
        self.ensure_one()

        if self.state not in ('draft', 'error'):
            raise UserError(_("Can only fetch in draft or error state"))

        self._log(f"Starting fetch from {self.date_from} to {self.date_to}")
        self.write({
            'state': 'fetching',
            'error_message': False,
        })

        try:
            # Call provider-specific fetch method
            raw_data = self.config_id._fetch_from_bank(self.date_from, self.date_to)

            # Store raw payload
            self.write({
                'raw_payload': json.dumps(raw_data, ensure_ascii=False, default=str),
                'payload_fetched_at': fields.Datetime.now(),
                'source_type': self.source_type or self.config_id._source_type(),
                'source_ref': self.source_ref or self.provider,
                'state': 'fetched',
            })
            self._log(f"Fetch completed, payload stored", data={'size': len(self.raw_payload)})

            # Auto-process after fetch
            self.action_process()

        except Exception as e:
            self._log(f"Fetch error: {str(e)}", level='error')
            self.write({
                'state': 'error',
                'error_message': str(e),
            })
            raise

    def action_process(self):
        """Process stored payload and create statement lines."""
        self.ensure_one()

        if self.state not in ('fetched', 'error'):
            raise UserError(_("Can only process in fetched or error state"))

        if not self.raw_payload:
            raise UserError(_("No payload to process. Fetch data first."))

        self._log("Starting payload processing")
        self.write({
            'state': 'processing',
            'error_message': False,
        })

        try:
            # Parse raw data
            raw_data = json.loads(self.raw_payload)
            transactions = self.config_id._parse_transactions(raw_data)

            self.transactions_count = len(transactions)
            self._log(f"Parsed {len(transactions)} transactions")

            # Фаза 1: виписка формується при імпорті як native-сутність.
            opening, closing = self.config_id._extract_balances(raw_data)
            statement = self._create_native_statement(
                transactions, opening, closing)
            imported = len(statement.line_ids) if statement else 0

            self.write({
                'bank_statement_id': statement.id if statement else False,
                'imported_count': imported,
                'updated_count': 0,
                'error_count': 0,
                'state': 'done',
            })

            # Update config last sync date
            self.config_id.write({
                'last_sync_date': fields.Datetime.now(),
            })

            self._log(f"Processing completed: {imported} statement line(s) "
                      f"imported into {statement.name if statement else '-'}")

        except Exception as e:
            self._log(f"Processing error: {str(e)}", level='error')
            self.write({
                'state': 'error',
                'error_message': str(e),
            })
            raise

    def action_reprocess(self):
        """Reprocess stored payload without fetching again."""
        self.ensure_one()

        if not self.raw_payload:
            raise UserError(_("No payload to reprocess"))

        # Reset counters
        self.write({
            'state': 'fetched',
            'imported_count': 0,
            'updated_count': 0,
            'error_count': 0,
            'error_message': False,
        })

        self._log("Starting reprocess of stored payload")
        return self.action_process()

    def action_reset_to_draft(self):
        """Reset job to draft state."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'raw_payload': False,
            'payload_fetched_at': False,
            'transactions_count': 0,
            'imported_count': 0,
            'updated_count': 0,
            'error_count': 0,
            'error_message': False,
        })
        # Delete related logs
        self.log_ids.unlink()

    @staticmethod
    def _trans_uid(trans):
        return str(trans.get('id') or trans.get('ref') or '').strip()

    @staticmethod
    def _trans_amount(trans):
        amount = trans.get('amount', 0)
        if isinstance(amount, str):
            amount = amount.replace(' ', '').replace(',', '.')
            try:
                amount = float(amount)
            except ValueError:
                amount = 0.0
        return float(amount or 0.0)

    def _trans_date(self, trans):
        d = trans.get('date')
        if isinstance(d, str):
            for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y'):
                try:
                    return datetime.strptime(d[:10], fmt).date()
                except ValueError:
                    continue
            return self.date_to or fields.Date.today()
        return d or self.date_to or fields.Date.today()

    def _create_native_statement(self, transactions, opening=None, closing=None):
        """Сформувати native-виписку (account.bank.statement) при імпорті.

        Виписка — унікальна сутність із метаданими джерела; володіє рядками
        (account.bank.statement.line з unique_import_id для дедупу). Баланси
        беруться з джерела (opening/closing); якщо їх немає — кінцевий баланс
        виводиться з рухів і виписка позначається як не звірена за балансом.
        """
        self.ensure_one()
        Statement = self.env['account.bank.statement']
        Line = self.env['account.bank.statement.line']
        journal = self.journal_id

        uids = [self._trans_uid(t) for t in transactions]
        seen = set()
        if any(uids):
            # Дедуп по вже імпортованих рухах у цьому журналі.
            Line.flush_model(['l10n_ua_import_uid', 'journal_id'])
            seen = set(Line.search([
                ('journal_id', '=', journal.id),
                ('l10n_ua_import_uid', 'in', [u for u in uids if u]),
            ]).mapped('l10n_ua_import_uid'))

        line_cmds = []
        total = 0.0
        for trans in transactions:
            uid = self._trans_uid(trans)
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            amount = self._trans_amount(trans)
            partner = self._match_partner(trans)
            line_cmds.append((0, 0, {
                'journal_id': journal.id,
                'date': self._trans_date(trans),
                'payment_ref': (trans.get('description')
                                or trans.get('purpose') or '/')[:2000] or '/',
                'amount': amount,
                'partner_id': partner.id if partner else False,
                'partner_name': trans.get('partner_name') or '',
                'account_number': trans.get('partner_iban') or '',
                'l10n_ua_import_uid': uid or False,
            }))
            total += amount

        if not line_cmds:
            return Statement.browse()

        verified = opening is not None and closing is not None
        bstart = opening if verified else 0.0
        bend = closing if verified else round(bstart + total, 2)
        statement = Statement.create({
            'name': self.name or _('Statement'),
            'journal_id': journal.id,
            'date': self.date_to or fields.Date.today(),
            'line_ids': line_cmds,
            'balance_start': bstart,
            'balance_end_real': bend,
            'l10n_ua_source_type': self.source_type or self.config_id._source_type(),
            'l10n_ua_source_ref': self.source_ref or self.provider or '',
            'l10n_ua_import_date': fields.Datetime.now(),
            'l10n_ua_sync_job_id': self.id,
            'l10n_ua_balance_verified': verified,
        })
        if verified and not statement.l10n_ua_balance_ok:
            self._log('Balance continuity mismatch: opening + Σ != closing '
                      '(%.2f + %.2f != %.2f)' % (bstart, total, bend),
                      level='warning')
        return statement

    def _match_partner(self, trans):
        """Match partner by EDRPOU, IPN or IBAN."""
        Partner = self.env['res.partner']
        partner = False

        edrpou = trans.get('partner_edrpou') or trans.get('CNTR_CRF') or ''
        iban = trans.get('partner_iban') or trans.get('CNTR_ACC') or ''

        if edrpou:
            partner = Partner.search([('edrpou', '=', edrpou)], limit=1)

        if not partner and iban:
            bank_account = self.env['res.partner.bank'].search([
                ('account_number', '=', iban)
            ], limit=1)
            if bank_account:
                partner = bank_account.partner_id

        return partner

    def action_view_logs(self):
        """View job logs."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Logs'),
            'res_model': 'l10n_ua.bank.sync.log',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
        }


class L10nUaBankSyncLog(models.Model):
    _name = 'l10n_ua.bank.sync.log'
    _description = 'Bank Sync Log Entry'
    _order = 'create_date desc'

    job_id = fields.Many2one(
        'l10n_ua.bank.sync.job',
        string='Job',
        required=True,
        ondelete='cascade',
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
    )
    level = fields.Selection(
        selection=[
            ('debug', 'Debug'),
            ('info', 'Info'),
            ('warning', 'Warning'),
            ('error', 'Error'),
        ],
        string='Level',
        default='info',
    )
    message = fields.Text(
        string='Message',
    )
    data = fields.Text(
        string='Data (JSON)',
        help='Additional data in JSON format',
    )
