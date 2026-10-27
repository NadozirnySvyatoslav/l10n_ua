"""EDO account: a connection of a company to an EDO service.

A provider module adds itself to ``provider`` and implements, under the name
``_<provider>_<operation>``, the operations below. Each one takes and returns
plain data, so the base module and the bridges never see the API:

* ``upload(payload)`` → provider document (dict). ``payload``: filename,
  content (bytes), title, number, date, amount, currency, recipient_edrpou,
  recipient_emails, category, recipient_signs_first.
* ``send(ref)`` — send an uploaded document to the counterparty.
* ``fetch(refs)`` → [provider document] — the current state of documents.
* ``incoming(date_from)`` → [provider document] — incoming documents.
* ``download(ref, kind)`` → (filename, bytes); kind is 'original' or
  'archive' (the file with the signatures).
* ``normalize(document)`` → values of ``l10n_ua.edo.document``.
* ``test()`` → a text shown to the user (the company the token belongs to).
* ``categories()`` → [(code, name)] — the document categories of the service.
* ``default_categories()`` (optional) → {report xmlid: category code} — the
  category each Ukrainian printed form goes under by default.
* ``bill_categories()`` (optional) → {category code} — the categories of
  incoming documents a vendor bill is made from (invoices, acts, waybills).
  Without it a bill can be made from any incoming document.
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaEdoAccount(models.Model):
    _name = 'l10n_ua.edo.account'
    _description = 'EDO Account'
    _inherit = ['mail.thread']
    _order = 'company_id, name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    provider = fields.Selection(
        [], string='Service', tracking=True,
        help='EDO service. Each service is a separate module (Вчасно — l10n_ua_edo_vchasno).')
    token = fields.Char(
        string='API Token', groups='base.group_system', copy=False,
        help='Token issued in the settings of the service. Kept only on the server.')
    edrpou = fields.Char(
        string='ЄДРПОУ', default=lambda self: self.env.company.edrpou,
        help='Code of the company in the service: documents are sent on its behalf.')
    incoming_date_from = fields.Date(
        string='Import Incoming From', default=fields.Date.context_today,
        help='Incoming documents created since this date are imported.')
    last_sync = fields.Datetime(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)
    document_ids = fields.One2many('l10n_ua.edo.document', 'account_id')
    category_ids = fields.One2many('l10n_ua.edo.category', 'account_id', string='Categories')
    category_rule_ids = fields.One2many(
        'l10n_ua.edo.category.rule', 'account_id', string='Categories of Printed Forms')
    document_count = fields.Integer(compute='_compute_document_count')

    def _compute_document_count(self):
        counts = dict(self.env['l10n_ua.edo.document']._read_group(
            [('account_id', 'in', self.ids)], ['account_id'], ['__count']))
        for account in self:
            account.document_count = counts.get(account, 0)

    @api.model
    def _for_company(self, company):
        """The active EDO account of a company, or an error the user can act on."""
        account = self.search([('company_id', '=', company.id), ('provider', '!=', False)], limit=1)
        if not account:
            raise UserError(_(
                'Company %(company)s has no EDO account. Add one in EDO → Configuration → Accounts.',
                company=company.display_name))
        return account

    # ── Provider dispatch ───────────────────────────────────

    def _call(self, operation, *args):
        self.ensure_one()
        if not self.provider:
            raise UserError(_('Choose the service of EDO account %s.', self.display_name))
        method = getattr(self, f'_{self.provider}_{operation}', None)
        if not method:
            raise UserError(_(
                'Service %(provider)s does not support «%(operation)s».',
                provider=self.provider, operation=operation))
        return method(*args)

    def _token(self):
        self.ensure_one()
        token = self.sudo().token
        if not token:
            raise UserError(_('EDO account %s has no API token.', self.display_name))
        return token

    # ── Actions ─────────────────────────────────────────────

    def action_test_connection(self):
        self.ensure_one()
        message = self._call('test')
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Connection works'), 'message': message, 'type': 'success'},
        }

    def action_sync(self):
        for account in self:
            account._sync()
        return True

    def action_load_categories(self):
        """Load the categories of the service and propose the category of each
        Ukrainian printed form."""
        Category = self.env['l10n_ua.edo.category'].with_context(active_test=False)
        for account in self:
            existing = {c.code: c for c in Category.search([('account_id', '=', account.id)])}
            for code, name in account._call('categories'):
                code = str(code)
                if code in existing:
                    existing[code].write({'name': name, 'active': True})
                else:
                    existing[code] = Category.create({'account_id': account.id, 'code': code, 'name': name})
            account._suggest_category_rules(existing)
        return True

    def _suggest_category_rules(self, categories):
        """Rules for the printed forms the provider knows, where none exists."""
        self.ensure_one()
        method = getattr(self, f'_{self.provider}_default_categories', None)
        if not method:
            return
        Rule = self.env['l10n_ua.edo.category.rule']
        mapped = set(self.category_rule_ids.report_id.ids)
        for xmlid, code in method().items():
            report = self.env.ref(xmlid, raise_if_not_found=False)
            category = categories.get(str(code))
            if report and category and report.id not in mapped:
                Rule.create({'account_id': self.id, 'report_id': report.id, 'category_id': category.id})
                mapped.add(report.id)

    def _category_for(self, report):
        """The category a printed form is sent under, or an empty recordset."""
        self.ensure_one()
        return self.category_rule_ids.filtered(lambda r: r.report_id == report)[:1].category_id

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('EDO Documents'),
            'res_model': 'l10n_ua.edo.document', 'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
        }

    @api.model
    def _cron_sync(self):
        # An account without a token is being set up (or is a demo): nothing to sync
        for account in self.search([('provider', '!=', False)]).filtered(lambda a: a.sudo().token):
            try:
                with self.env.cr.savepoint():
                    account._sync()
            except Exception as error:  # noqa: BLE001 — one account must not stop the others
                _logger.warning('EDO account %s: sync failed: %s', account.id, error)
                account.last_error = str(error)

    # ── Synchronisation ─────────────────────────────────────

    def _sync(self):
        """Refresh the open outgoing documents and import the incoming ones."""
        self.ensure_one()
        Document = self.env['l10n_ua.edo.document']
        open_docs = Document.search([
            ('account_id', '=', self.id), ('provider_ref', '!=', False),
            ('state', 'not in', Document._FINAL_STATES)])
        if open_docs:
            by_ref = {doc.provider_ref: doc for doc in open_docs}
            for data in self._call('fetch', list(by_ref)):
                vals = self._call('normalize', data)
                doc = by_ref.get(vals.get('provider_ref'))
                if doc:
                    doc._apply_provider_vals(vals)
        for data in self._call('incoming', self.incoming_date_from):
            vals = self._call('normalize', data)
            Document._upsert_incoming(self, vals)
        self.write({'last_sync': fields.Datetime.now(), 'last_error': False})
