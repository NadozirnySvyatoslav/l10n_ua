"""Форма № 5 «Примітки до річної фінансової звітності» — stored report.

The layout is in ``l10n_ua_notes_data``. «Calculate» fills from the ledger
what the chart of accounts tells unambiguously (Інструкція № 291):

* I, II — the original cost per subaccount of 12 and 10/11: balance at the
  start (graph 3) and the end (14), debit (5) and credit (8) turnover. The
  depreciation is not kept per group on the chart (131/132/133 have no
  subaccounts per kind of asset): graphs 4, 7, 9, 10, 13, 15 are entered by
  hand; ``depreciation_hint`` gives the totals of 131, 132, 133 to split;
* III — debit turnover (3) and balance (4) of 151–155, the rest of 15 in 330;
* V — the incomes (3) and expenses (4) of the period per subaccount of 71–74,
  94–97, without the closing through 79;
* VI — the balances of 30, 31, 33, 351; VII — opening (3), credit (4) and
  debit (6) turnover and closing (9) of 471–473, 478 and of 38;
* VIII — the balances of 20–28; IX — rows 1125/1155 of Форма № 1 and the
  open items of 36 and 37/68 by age; X — debit turnover of 947 and 375;
* XII — 981, the balances of 17 and 54; XIII — credit turnover of 13.

Everything else (IV, XI, XIV, XV, the indicators «з рядка …») is entered by
hand. The rows «Разом»/«усього» (``NOTES_SUMS``) are added up from their
parts, graph by graph, after every change. Amounts are in thousands of
hryvnias without decimals (DGdecimal0), rounded half away from zero; the
totals are added up from the rounded rows.
"""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

from .l10n_ua_notes_data import (
    NOTES_CAPEX_ACCOUNTS, NOTES_CASH_ACCOUNTS, NOTES_FIXED_ACCOUNTS,
    NOTES_INCOME_EXPENSE_ACCOUNTS, NOTES_INTANGIBLE_ACCOUNTS,
    NOTES_INVENTORY_ACCOUNTS, NOTES_PROVISION_ACCOUNTS, NOTES_SECTIONS,
    NOTES_SUMS, notes_rows, notes_xml_element,
)
from .l10n_ua_pnl_report import pnl_closing_move_domain

GRAPH_FIELDS = [f'g{n}' for n in range(3, 20)]
EDITABLE_KINDS = ('row', 'blank', 'note')


def thousands(amount):
    return float_round((amount or 0.0) / 1000.0, precision_digits=0, rounding_method='HALF-UP')


def longest_prefix(code, mapping):
    """The key of ``mapping`` (key → prefixes) whose prefix is the longest
    one ``code`` starts with, or None."""
    best, best_len = None, 0
    for key, prefixes in mapping.items():
        for prefix in prefixes:
            if code.startswith(prefix) and len(prefix) > best_len:
                best, best_len = key, len(prefix)
    return best


class L10nUaNotesReport(models.Model):
    _name = 'l10n_ua.notes.report'
    _description = 'Notes to the Annual Financial Statements (Form No.5)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(
        string='Year Start', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
    )
    date_to = fields.Date(
        string='Year End', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=12, day=31),
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')], default='draft', tracking=True)
    line_ids = fields.One2many('l10n_ua.notes.report.line', 'report_id', string='Lines')
    depreciation_hint = fields.Char(
        string='Depreciation to Split', readonly=True,
        help='Balances of 131, 132 and 133 at the end of the year, in thousands. The chart '
             'of accounts keeps no depreciation per kind of asset: enter graphs 4 and 15 '
             'of sections I and II per row so that the rows «Разом» match them.')
    note = fields.Text(string='Notes')

    @api.depends('date_to')
    def _compute_name(self):
        for rec in self:
            rec.name = f'Примітки до річної фінансової звітності за {rec.date_to.year} рік' \
                if rec.date_to else 'Примітки до річної фінансової звітності'

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_('The start of the period must not be after its end.'))

    # ── Actions ─────────────────────────────────────────────

    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Cannot recalculate a confirmed report. Set it back to draft first.'))
            rec.line_ids.unlink()
            rec._generate_lines()

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Calculate the report before confirming.'))
            rec.state = 'confirmed'

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_accounting.action_report_notes').report_action(self)

    # ── Ledger ──────────────────────────────────────────────

    def _domain(self):
        return [('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted')]

    def _per_account(self, domain, aggregates=('debit:sum', 'credit:sum', 'balance:sum')):
        """[(account code, debit, credit, balance)] of the journal items of ``domain``."""
        MoveLine = self.env['account.move.line'].with_company(self.company_id)
        return [
            (account.with_company(self.company_id).code or '', *values)
            for account, *values in MoveLine._read_group(
                self._domain() + domain, ['account_id'], list(aggregates))
        ]

    def _by_row(self, mapping, domain):
        """{row: (debit, credit, balance)} of the accounts of ``mapping``."""
        result = {}
        for code, debit, credit, balance in self._per_account(domain):
            row = longest_prefix(code, mapping)
            if row:
                d, c, b = result.get(row, (0.0, 0.0, 0.0))
                result[row] = (d + debit, c + credit, b + balance)
        return result

    def _ledger_values(self):
        """{(row, graph): amount in hryvnias} filled from the ledger."""
        self.ensure_one()
        start = [('date', '<', self.date_from)]
        end = [('date', '<=', self.date_to)]
        period = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        v = {}

        # I, II: original cost per subaccount
        for mapping in (NOTES_INTANGIBLE_ACCOUNTS, NOTES_FIXED_ACCOUNTS):
            for row, (_d, _c, balance) in self._by_row(mapping, start).items():
                v[(row, 3)] = balance
            for row, (debit, credit, _b) in self._by_row(mapping, period).items():
                v[(row, 5)], v[(row, 8)] = debit, credit
            for row, (_d, _c, balance) in self._by_row(mapping, end).items():
                v[(row, 14)] = balance

        # III: capital investments
        capex = dict(NOTES_CAPEX_ACCOUNTS, **{'330': ('15',)})
        for row, (debit, _c, _b) in self._by_row(capex, period).items():
            v[(row, 3)] = debit
        for row, (_d, _c, balance) in self._by_row(capex, end).items():
            v[(row, 4)] = balance

        # V: incomes and expenses, without the closing through 79
        no_closing = period + pnl_closing_move_domain(
            self.env, self.company_id, self.date_from, self.date_to)
        accounts = self._per_account(no_closing)
        for (row, graph), prefixes in NOTES_INCOME_EXPENSE_ACCOUNTS.items():
            for code, debit, credit, _b in accounts:
                if code.startswith(prefixes):
                    v[(row, graph)] = v.get((row, graph), 0.0) + (
                        credit - debit if graph == 3 else debit - credit)

        # VI: cash; VIII: inventories — balances at the end
        for mapping, graph in ((NOTES_CASH_ACCOUNTS, 3), (NOTES_INVENTORY_ACCOUNTS, 3)):
            for row, (_d, _c, balance) in self._by_row(mapping, end).items():
                v[(row, graph)] = balance

        # VII: provisions (credit balances)
        for row, (_d, _c, balance) in self._by_row(NOTES_PROVISION_ACCOUNTS, start).items():
            v[(row, 3)] = -balance
        for row, (debit, credit, _b) in self._by_row(NOTES_PROVISION_ACCOUNTS, period).items():
            v[(row, 4)], v[(row, 6)] = credit, debit
        for row, (_d, _c, balance) in self._by_row(NOTES_PROVISION_ACCOUNTS, end).items():
            v[(row, 9)] = -balance

        # IX: receivables — rows of Form 1, open items by age
        balance = self.env['l10n_ua.balance.report'].new({'company_id': self.company_id.id})
        form1, _unmapped = balance._get_row_amounts(self.date_to)
        v[('940', 3)] = form1.get('receivables_goods', 0.0)
        v[('950', 3)] = form1.get('other_current_receivables', 0.0)
        v.update(self._receivables_by_age())

        # X: shortages
        for row, prefix in (('960', '947'), ('970', '375')):
            v[(row, 3)] = sum(d for code, d, c, b in self._per_account(period) if code.startswith(prefix))

        # XII: income tax
        tax = sum(d - c for code, d, c, b in self._per_account(no_closing) if code.startswith('981'))
        dta = lambda dom: sum(b for code, d, c, b in self._per_account(dom) if code.startswith('17'))  # noqa: E731
        dtl = lambda dom: -sum(b for code, d, c, b in self._per_account(dom) if code.startswith('54'))  # noqa: E731
        v[('1210', 3)] = v[('1241', 3)] = tax
        v[('1220', 3)], v[('1225', 3)] = dta(start), dta(end)
        v[('1230', 3)], v[('1235', 3)] = dtl(start), dtl(end)
        v[('1242', 3)] = v[('1220', 3)] - v[('1225', 3)]
        v[('1243', 3)] = v[('1235', 3)] - v[('1230', 3)]

        # XIII: depreciation charged
        v[('1300', 3)] = sum(c for code, d, c, b in self._per_account(period) if code.startswith('13'))
        return v

    def _receivables_by_age(self):
        """Open items of 36 (row 940) and 37, 68 (950) by the months since
        they arose: graphs 4 (up to 12), 5 (12–18), 6 (18–36)."""
        MoveLine = self.env['account.move.line'].with_company(self.company_id)
        lines = MoveLine.search(self._domain() + [
            ('date', '<=', self.date_to),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('amount_residual', '>', 0),
        ])
        result = {}
        limits = [(self.date_to - relativedelta(months=12), 4),
                  (self.date_to - relativedelta(months=18), 5),
                  (self.date_to - relativedelta(months=36), 6)]
        for line in lines:
            code = line.account_id.with_company(self.company_id).code or ''
            row = '940' if code.startswith('36') else '950' if code.startswith(('37', '68')) else None
            if not row:
                continue
            for limit, graph in limits:
                if line.date > limit:
                    result[(row, graph)] = result.get((row, graph), 0.0) + line.amount_residual
                    break
        return result

    def _generate_lines(self):
        self.ensure_one()
        values = self._ledger_values()
        vals_list = []
        for section, seq, code, name, kind, graphs in notes_rows():
            vals = {
                'report_id': self.id,
                'section': section,
                'sequence': seq,
                'code': code,
                'name': name,
                'kind': kind,
                'graphs': ','.join(str(g) for g in graphs),
            }
            for graph in graphs:
                vals[f'g{graph}'] = thousands(values.get((code, graph), 0.0))
            vals_list.append(vals)
        self.env['l10n_ua.notes.report.line'].create(vals_list)
        self._recompute_totals()
        hint = []
        for prefix in ('131', '132', '133'):
            amount = -sum(b for code, d, c, b in self._per_account([('date', '<=', self.date_to)])
                          if code.startswith(prefix))
            if amount:
                hint.append(f'{prefix}: {thousands(amount):.0f}')
        self.depreciation_hint = ', '.join(hint) or False

    def _recompute_totals(self):
        for rec in self:
            lines = {line.code: line for line in rec.line_ids if line.code}
            # Totals of totals (1430 = 1410 + 1420, 1540) after their parts
            for total in sorted(NOTES_SUMS, key=lambda c: c in ('1430', '1540')):
                line = lines.get(total)
                if not line:
                    continue
                vals = {}
                for graph in line.graph_list():
                    vals[f'g{graph}'] = sum(
                        lines[part][f'g{graph}'] for part in NOTES_SUMS[total]
                        if part in lines and graph in lines[part].graph_list())
                line.with_context(l10n_ua_notes_no_recompute=True).write(vals)

    def _xml_values(self):
        """{'R0010G3': 12, 'R0060G1S': 'name', …} for J0901301. Empty cells
        are left out."""
        self.ensure_one()
        values = {}
        for line in self.line_ids.filtered(lambda l: l.code and l.kind != 'title'):
            if line.kind == 'blank' and line.label:
                values[notes_xml_element(line.code, '1S')] = line.label
            for graph in line.graph_list():
                amount = int(line[f'g{graph}'])
                if amount:
                    values[notes_xml_element(line.code, graph)] = amount
        return values

    @api.model
    def _section_graphs(self, section):
        """(graphs, {graph: title}) of a section, for the printed form."""
        for number, _title, graphs, titles, _lines in NOTES_SECTIONS:
            if number == section:
                return graphs, titles
        return (), {}


class L10nUaNotesReportLine(models.Model):
    _name = 'l10n_ua.notes.report.line'
    _description = 'Notes to the Financial Statements Line'
    _order = 'sequence, id'

    report_id = fields.Many2one('l10n_ua.notes.report', required=True, ondelete='cascade')
    section = fields.Char(string='Section')
    sequence = fields.Integer()
    code = fields.Char(string='Row Code')
    name = fields.Char(string='Line Name')
    label = fields.Char(string='Own Name', help='Name of a row the form leaves blank (060, 760, …).')
    kind = fields.Selection(
        [('section', 'Section'), ('title', 'Title'), ('row', 'Row'), ('blank', 'Row Named by the Company'),
         ('note', 'Indicator')], string='Kind')
    graphs = fields.Char(string='Graphs', help='Graphs of the form this row has.')
    is_total = fields.Boolean(compute='_compute_is_total')
    for _graph in range(3, 20):
        locals()[f'g{_graph}'] = fields.Float(string=f'Gr. {_graph}', digits=(16, 0))
    del _graph

    @api.depends('code')
    def _compute_is_total(self):
        for line in self:
            line.is_total = line.code in NOTES_SUMS

    def graph_list(self):
        self.ensure_one()
        return [int(g) for g in (self.graphs or '').split(',') if g]

    def write(self, vals):
        changes = [f for f in GRAPH_FIELDS if f in vals]
        if changes and not self.env.context.get('l10n_ua_notes_no_recompute'):
            if self.filtered(lambda l: l.report_id.state != 'draft'):
                raise UserError(_('A confirmed report cannot be changed. Set it back to draft first.'))
            for line in self:
                allowed = {f'g{g}' for g in line.graph_list()}
                if line.code in NOTES_SUMS or line.kind not in EDITABLE_KINDS \
                        or any(f not in allowed and vals[f] for f in changes):
                    raise UserError(_(
                        'Row %(code)s: the totals are added up from their rows, and a graph '
                        'marked «Х» on the form has no amount.', code=line.code or line.name))
            res = super().write(vals)
            self.report_id._recompute_totals()
            return res
        return super().write(vals)
