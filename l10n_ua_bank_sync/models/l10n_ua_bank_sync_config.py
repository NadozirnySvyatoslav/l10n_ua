import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaBankSyncConfig(models.Model):
    _name = 'l10n_ua.bank.sync.config'
    _description = 'Bank Sync Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
    )
    active = fields.Boolean(
        default=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        tracking=True,
    )
    bank_account_id = fields.Many2one(
        'res.partner.bank',
        string='Bank Account',
        related='journal_id.bank_account_id',
        readonly=True,
    )
    provider = fields.Selection(
        selection=[
            ('manual', 'Manual'),
        ],
        string='Provider',
        required=True,
        default='manual',
        tracking=True,
    )

    # Тип обміну (керує видимістю кнопок: онлайн-синхронізація vs імпорт файлу)
    exchange_type = fields.Selection([
        ('online', 'Online (API)'),
        ('file', 'File exchange'),
        ('manual', 'Manual'),
    ], string='Exchange Type', compute='_compute_exchange_type', store=True,
        help='Онлайн-провайдери синхронізуються через API; файлові — імпортом '
             'виписки з файлу.')

    @api.depends('provider')
    def _compute_exchange_type(self):
        for rec in self:
            st = rec._source_type()
            rec.exchange_type = (
                'file' if st == 'file'
                else 'manual' if st == 'manual'
                else 'online')

    # Sync settings
    auto_sync = fields.Boolean(
        string='Auto Sync',
        default=False,
        help='Enable automatic synchronization via scheduled action',
    )
    sync_interval_hours = fields.Integer(
        string='Sync Interval (hours)',
        default=24,
    )
    default_days_back = fields.Integer(
        string='Default Days Back',
        default=7,
        help='Default number of days to fetch statements for',
    )

    # Status
    last_sync_date = fields.Datetime(
        string='Last Sync',
        readonly=True,
    )
    last_sync_job_id = fields.Many2one(
        'l10n_ua.bank.sync.job',
        string='Last Sync Job',
        readonly=True,
    )
    job_ids = fields.One2many(
        'l10n_ua.bank.sync.job',
        'config_id',
        string='Sync Jobs',
    )
    job_count = fields.Integer(
        string='Job Count',
        compute='_compute_job_count',
    )

    @api.depends('job_ids')
    def _compute_job_count(self):
        for rec in self:
            rec.job_count = len(rec.job_ids)

    def action_view_jobs(self):
        """Open list of sync jobs for this config."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Jobs'),
            'res_model': 'l10n_ua.bank.sync.job',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
        }

    def action_test_connection(self):
        """Кінець ланцюжка `super()` для перевірки з'єднання.

        Кожен модуль банку (`l10n_ua_bank_mono`, `l10n_ua_bank_privat`, …)
        розширює цю саму модель і перевіряє лише свого провайдера, а решту
        передає далі по MRO. Раніше передача була обгорнута в
        `hasattr(super(), 'action_test_connection')`, бо базової реалізації не
        існувало й ланцюжок упирався в порожнечу — при цьому `hasattr` мовчки
        ковтав би й будь-яку іншу помилку доступу. Тепер кінець ланцюжка є, і
        провайдери викликають `super()` беззастережно.

        Провайдер, який перевірки не має (як-от «Manual» чи обмін файлами),
        доходить сюди й отримує зрозуміле повідомлення замість тиші.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Nothing to test'),
                'message': _(
                    'Provider "%s" has no connection to test: statements for '
                    'it are imported from a file, not fetched over an API.'
                ) % dict(self._fields['provider']._description_selection(
                    self.env)).get(self.provider, self.provider),
                'type': 'warning',
            },
        }

    def action_sync_now(self):
        """Create and run sync job for default period."""
        self.ensure_one()
        date_to = fields.Date.today()
        date_from = date_to - timedelta(days=self.default_days_back)
        return self._create_and_run_job(date_from, date_to)

    def action_open_sync_wizard(self):
        """Open wizard to select custom date range."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Bank Statements'),
            'res_model': 'l10n_ua.bank.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_config_id': self.id,
                'default_date_from': fields.Date.today() - timedelta(days=self.default_days_back),
                'default_date_to': fields.Date.today(),
            },
        }

    def _create_and_run_job(self, date_from, date_to):
        """Create sync job and start fetching."""
        self.ensure_one()
        job = self.env['l10n_ua.bank.sync.job'].create({
            'config_id': self.id,
            'date_from': date_from,
            'date_to': date_to,
        })
        self.write({
            'last_sync_job_id': job.id,
            'last_sync_date': fields.Datetime.now(),
        })
        job.action_fetch()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Job'),
            'res_model': 'l10n_ua.bank.sync.job',
            'view_mode': 'form',
            'res_id': job.id,
        }

    def _fetch_from_bank(self, date_from, date_to):
        """
        Fetch raw data from bank API.
        Override in provider-specific modules.

        Returns:
            dict: Raw API response data to be stored in job
        """
        raise NotImplementedError(
            _("Provider '%s' does not implement _fetch_from_bank method") % self.provider
        )

    def _parse_transactions(self, raw_data):
        """
        Parse raw API data into transaction list.
        Override in provider-specific modules.

        Args:
            raw_data: dict from _fetch_from_bank

        Returns:
            list of dicts with transaction data
        """
        raise NotImplementedError(
            _("Provider '%s' does not implement _parse_transactions method") % self.provider
        )

    def _extract_balances(self, raw_data):
        """Витягти (opening, closing) баланси рахунку з даних джерела.

        Перевизначає провайдер, чиє джерело несе баланси (файл виписки з
        opening/closing, або API-endpoint балансу). Повертає (None, None),
        якщо баланси недоступні — тоді native-виписка формується з виведеним
        (недостовірним) кінцевим балансом (`l10n_ua_balance_verified = False`).
        """
        return (None, None)

    def _statement_line_vals(self, trans):
        """Додаткові значення рядка виписки з руху `trans` (dict з
        `_parse_transactions`). Перевизначає провайдер, чиє джерело несе
        більше, ніж базові поля (номер квитанції, зовнішній ідентифікатор).
        """
        return {}

    def _source_type(self):
        """Тип джерела імпорту (file / api / manual). Перевизначає провайдер."""
        self.ensure_one()
        return 'manual' if self.provider == 'manual' else 'api'

    def _file_to_payload(self, content, filename=None):
        """Перетворити байти файлу виписки на raw_payload для _parse_transactions.

        Перевизначає файловий провайдер (VST: cp1251 CSV → {'csv': text}).
        Дозволяє єдиному майстру імпорту працювати з будь-яким файловим
        провайдером без знання його формату.
        """
        raise UserError(_(
            "Провайдер '%s' не підтримує імпорт з файлу.") % self.provider)

    def _is_sync_due(self, now=None):
        """Whether this config should sync now, per its ``sync_interval_hours``.

        Due when never synced, when the interval is not set (<=0 → every tick),
        or when ``sync_interval_hours`` has elapsed since ``last_sync_date``.
        """
        self.ensure_one()
        now = now or fields.Datetime.now()
        interval = max(self.sync_interval_hours or 0, 0)
        if self.last_sync_date and interval:
            return now >= self.last_sync_date + timedelta(hours=interval)
        return True

    @api.model
    def _cron_auto_sync(self):
        """Scheduled auto-sync of enabled configurations.

        The cron runs frequently (hourly); each config decides whether it is
        actually due via its own ``sync_interval_hours``. Failures are isolated
        per config with a savepoint so one broken feed does not abort the rest.
        """
        now = fields.Datetime.now()
        configs = self.search([('auto_sync', '=', True)])
        for config in configs:
            if not config._is_sync_due(now):
                continue
            try:
                with self.env.cr.savepoint():
                    config.action_sync_now()
            except Exception as e:
                _logger.exception("Auto-sync failed for %s: %s", config.name, e)
