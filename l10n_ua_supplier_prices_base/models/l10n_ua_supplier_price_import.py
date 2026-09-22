import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..tools.json_path import resolve, resolve_first
from ..tools.transforms import apply_transform, TransformError

_logger = logging.getLogger(__name__)


STATE_TRANSITIONS = {
    'draft': ('fetching', 'error'),
    'fetching': ('fetched', 'error'),
    'fetched': ('parsing', 'error'),
    'parsing': ('parsed', 'error'),
    'parsed': ('applying', 'parsing', 'error'),  # reparse allowed
    'applying': ('done', 'error'),
    'error': ('draft',),
    'done': ('parsing',),  # allow re-parse after done (не re-fetch)
}


class L10nUaSupplierPriceImport(models.Model):
    _name = 'l10n_ua.supplier.price.import'
    _description = 'Supplier Price Import'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_imported desc, id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, default='/', tracking=True)
    source_id = fields.Many2one(
        'l10n_ua.supplier.price.source',
        string='Source',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    partner_id = fields.Many2one(
        related='source_id.partner_id', store=True, readonly=True, string='Supplier',
    )
    company_id = fields.Many2one(
        related='source_id.company_id', store=True, readonly=True,
    )
    date_imported = fields.Datetime(
        string='Date',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('fetching', 'Fetching'),
            ('fetched', 'Fetched'),
            ('parsing', 'Parsing'),
            ('parsed', 'Parsed'),
            ('applying', 'Applying'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        default='draft',
        required=True,
        tracking=True,
        readonly=True,
    )
    raw_file = fields.Binary(
        string='Raw File',
        attachment=True,
        help='Збережений файл після fetch — використовується для повторного парсингу',
    )
    raw_filename = fields.Char(string='Filename')
    error_log = fields.Text(string='Error Log', readonly=True)

    line_ids = fields.One2many(
        'l10n_ua.supplier.price.import.line',
        'import_id',
        string='Lines',
    )
    line_count = fields.Integer(compute='_compute_line_stats', store=True)
    matched_count = fields.Integer(compute='_compute_line_stats', store=True)
    unknown_count = fields.Integer(compute='_compute_line_stats', store=True)
    error_count = fields.Integer(compute='_compute_line_stats', store=True)

    @api.depends('line_ids', 'line_ids.status')
    def _compute_line_stats(self):
        for imp in self:
            lines = imp.line_ids
            imp.line_count = len(lines)
            imp.matched_count = len(lines.filtered(lambda l: l.status in ('matched', 'created')))
            imp.unknown_count = len(lines.filtered(lambda l: l.status == 'unknown'))
            imp.error_count = len(lines.filtered(lambda l: l.status == 'error'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.supplier.price.import'
                ) or '/'
        return super().create(vals_list)

    def _set_state(self, new_state, error_message=None):
        """Validate transition then update state. NEVER use direct write({'state': ...})."""
        for imp in self:
            allowed = STATE_TRANSITIONS.get(imp.state, ())
            if new_state not in allowed:
                raise UserError(_(
                    "Invalid state transition: %(from)s → %(to)s. Allowed: %(allowed)s",
                    **{'from': imp.state, 'to': new_state, 'allowed': allowed or '(terminal)'},
                ))
            vals = {'state': new_state}
            if error_message is not None:
                vals['error_log'] = error_message
            super(L10nUaSupplierPriceImport, imp).write(vals)

    # === Action buttons (manual control) ===

    def action_fetch(self):
        """draft → fetching → fetched. Якщо fetch впав — state=error, error_log заповнено."""
        for imp in self:
            imp._set_state('fetching')
            try:
                imp._do_fetch()
            except Exception as e:
                _logger.exception("Fetch failed for import %s", imp.name)
                imp._set_state('error', error_message=f'Fetch error: {e}')
                imp.message_post(body=_("Fetch failed: %s") % e)
                continue
            imp._set_state('fetched')
        return True

    def action_parse(self):
        """fetched/parsed → parsing → parsed. Reparse дозволено з parsed (скидає line_ids)."""
        for imp in self:
            if not imp.raw_file:
                imp._set_state('error', error_message='No raw file to parse. Run Fetch first.')
                continue
            imp._set_state('parsing')
            try:
                imp.line_ids.unlink()
                imp._do_parse()
            except Exception as e:
                _logger.exception("Parse failed for import %s", imp.name)
                imp._set_state('error', error_message=f'Parse error: {e}')
                imp.message_post(body=_("Parse failed: %s") % e)
                continue
            imp._set_state('parsed')
        return True

    def action_apply(self):
        """parsed → applying → done. Створює/оновлює product.supplierinfo."""
        for imp in self:
            if not imp.line_ids:
                imp._set_state('error', error_message='No lines to apply. Run Parse first.')
                continue
            imp._set_state('applying')
            try:
                imp._do_apply()
            except Exception as e:
                _logger.exception("Apply failed for import %s", imp.name)
                imp._set_state('error', error_message=f'Apply error: {e}')
                imp.message_post(body=_("Apply failed: %s") % e)
                continue
            imp._set_state('done')
        return True

    def action_restart(self):
        """error → draft. Очищує error_log."""
        for imp in self:
            if imp.state != 'error':
                raise UserError(_("Restart is only allowed from error state."))
            super(L10nUaSupplierPriceImport, imp).write({
                'state': 'draft',
                'error_log': False,
            })
        return True

    # === Pluggable hooks for extension modules ===

    def _do_fetch(self):
        """Override per fetcher_type. Must populate raw_file and raw_filename."""
        self.ensure_one()
        if self.source_id.fetcher_type == 'manual':
            if not self.raw_file:
                raise UserError(_("Upload a file before fetching (manual mode)."))
            return
        raise UserError(_(
            "No fetcher implementation for type '%s'. "
            "Install the corresponding module (e.g. l10n_ua_supplier_prices_api).",
            self.source_id.fetcher_type,
        ))

    def _do_parse(self):
        """Dispatch на парсер конкретного типу. Розширення override через if-chain
        додаючи свої гілки перед super()."""
        self.ensure_one()
        if self.source_id.parser_type == 'json':
            return self._parse_json()
        raise UserError(_(
            "No parser implementation for type '%s'. "
            "Install the corresponding module (e.g. l10n_ua_supplier_prices_xml).",
            self.source_id.parser_type,
        ))

    def _get_parser_config(self):
        """Розпарсити parser_config JSON. Повертає {} якщо порожнє/невалідне."""
        self.ensure_one()
        raw = self.source_id.mapping_id.parser_config
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            raise UserError(_("Invalid parser_config JSON on mapping '%s'") %
                            self.source_id.mapping_id.name)

    def _parse_json(self):
        """Парсер JSON: завантажує raw_file, розгортає mapping, створює line_ids."""
        self.ensure_one()
        try:
            raw_bytes = self.raw_file.content
            data = json.loads(raw_bytes.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            raise UserError(_("Invalid JSON file: %s") % e)

        mapping = self.source_id.mapping_id
        if not mapping:
            raise UserError(_("Source has no mapping configured."))

        if mapping.record_path:
            records = resolve(data, mapping.record_path)
            # Shorthand: якщо path вказує на список (без [*]) — розгортаємо
            if len(records) == 1 and isinstance(records[0], list):
                records = records[0]
        else:
            records = data if isinstance(data, list) else [data]
        if not records:
            raise UserError(_(
                "No records found at record_path '%s'. Check mapping configuration.",
                mapping.record_path or '(root)',
            ))

        deadline = datetime.now() + timedelta(seconds=self.source_id.parse_timeout)
        Line = self.env['l10n_ua.supplier.price.import.line']
        Currency = self.env['res.currency']
        currency_cache = {}

        for sequence, record in enumerate(records, start=10):
            if datetime.now() > deadline:
                raise UserError(_(
                    "Parse timeout (%(t)ss) exceeded after %(n)s records.",
                    t=self.source_id.parse_timeout, n=sequence - 10,
                ))
            vals = {'import_id': self.id, 'sequence': sequence}
            for field in mapping.field_ids:
                raw_value = resolve_first(record, field.source_path)
                if raw_value is None or raw_value == '':
                    if field.required and not field.default_value:
                        raise UserError(_(
                            "Required field '%(t)s' missing at record %(n)s (path: %(p)s)",
                            t=field.target, n=sequence - 10, p=field.source_path,
                        ))
                    raw_value = field.default_value
                if raw_value is None or raw_value == '':
                    continue
                try:
                    value = apply_transform(raw_value, field.transform, field.transform_param)
                except TransformError as e:
                    raise UserError(_(
                        "Transform error on field '%(t)s' (record %(n)s): %(e)s",
                        t=field.target, n=sequence - 10, e=str(e),
                    ))
                self._assign_field_value(vals, field.target, value, currency_cache, Currency)

            if not vals.get('supplier_sku'):
                continue
            Line.create(vals)

    def _assign_field_value(self, vals, target, value, currency_cache, Currency):
        """Розкладає значення з mapping field у відповідне поле import.line."""
        if target == 'sku':
            vals['supplier_sku'] = str(value)
        elif target == 'name':
            vals['supplier_name'] = str(value)
        elif target == 'barcode':
            vals['barcode'] = str(value)
        elif target == 'description':
            vals['description'] = str(value)
        elif target == 'price':
            vals['price'] = float(value)
        elif target == 'qty_min':
            vals['qty_min'] = float(value)
        elif target == 'uom':
            vals['uom_text'] = str(value)
        elif target == 'date_valid':
            vals['date_valid'] = value
        elif target == 'currency':
            code = str(value).upper().strip()
            if code not in currency_cache:
                currency_cache[code] = Currency.with_context(
                    active_test=False
                ).search([('name', '=', code)], limit=1)
            currency = currency_cache[code]
            if currency:
                vals['currency_id'] = currency.id

    def _do_apply(self):
        """Default apply — створює/оновлює product.supplierinfo для кожної matched line."""
        self.ensure_one()
        Supplierinfo = self.env['product.supplierinfo']
        chunk_size = 500
        lines = self.line_ids
        applied = 0
        deadline = datetime.now() + timedelta(seconds=self.source_id.apply_timeout)

        for offset in range(0, len(lines), chunk_size):
            if datetime.now() > deadline:
                raise UserError(_(
                    "Apply timeout (%(t)ss) exceeded after %(n)s lines. "
                    "Increase apply_timeout on source or split import.",
                    t=self.source_id.apply_timeout, n=applied,
                ))
            chunk = lines[offset:offset + chunk_size]
            for line in chunk:
                line._apply_to_supplierinfo()
                applied += 1
            self.env.cr.commit()

    # === Watchdog cron ===

    @api.model
    def _cron_watchdog(self):
        """Знаходить imports застряглі в проміжних станах і переводить у error."""
        in_flight_states = ('fetching', 'parsing', 'applying')
        candidates = self.search([('state', 'in', in_flight_states)])
        now = datetime.now()
        stuck_count = 0
        for imp in candidates:
            timeout_minutes = imp.source_id.watchdog_timeout_minutes
            stuck_for = (now - fields.Datetime.from_string(imp.write_date)).total_seconds() / 60
            if stuck_for >= timeout_minutes:
                imp._set_state('error', error_message=_(
                    "Watchdog: stuck in state %(s)s for %(m).0f minutes (limit %(l)s).",
                    s=imp.state, m=stuck_for, l=timeout_minutes,
                ))
                stuck_count += 1
        if stuck_count:
            _logger.warning("Watchdog: marked %d stuck imports as error", stuck_count)
        return stuck_count

    @api.model
    def _cron_auto_sync(self):
        """Створює нові draft imports для джерел з auto_sync_active=True."""
        Source = self.env['l10n_ua.supplier.price.source']
        sources = Source.search([('auto_sync_active', '=', True), ('active', '=', True)])
        now = datetime.now()
        created = 0
        for source in sources:
            if source.last_sync_date:
                next_sync = fields.Datetime.from_string(source.last_sync_date) + \
                            timedelta(hours=source.sync_interval_hours)
                if now < next_sync:
                    continue
            imp = self.create({'source_id': source.id})
            try:
                imp.action_fetch()
                imp.action_parse()
                imp.action_apply()
                source.last_sync_date = now
                created += 1
            except Exception as e:
                _logger.error("Auto-sync failed for source %s: %s", source.name, e)
        return created
