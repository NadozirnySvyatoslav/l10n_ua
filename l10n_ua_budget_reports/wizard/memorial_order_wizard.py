"""Universal wizard for Memorial Orders 1-17."""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError


# Перелік МО з Інструкції з бухобліку в держсекторі. Кожен МО — це
# накопичувальна відомість руху по певному набору рахунків / операцій.
MO_CHOICES = [
    ('mo_1', 'МО-1 Накопичувальна відомість по касі'),
    ('mo_2', 'МО-2 Рух коштів загального фонду'),
    ('mo_3', 'МО-3 Рух коштів спеціального фонду'),
    ('mo_4', 'МО-4 Рух коштів інших фондів'),
    ('mo_5', 'МО-5 Розрахункові відомості із заробітної плати'),
    ('mo_6', 'МО-6 Розрахунки з постачальниками'),
    ('mo_7', 'МО-7 Розрахунки в порядку планових платежів'),
    ('mo_8', 'МО-8 Розрахунки з підзвітними особами'),
    ('mo_9', 'МО-9 Вибуття та переміщення необоротних активів'),
    ('mo_10', 'МО-10 Вибуття та переміщення малоцінних активів'),
    ('mo_11', 'МО-11 Надходження продуктів харчування'),
    ('mo_12', 'МО-12 Витрачання продуктів харчування'),
    ('mo_13', 'МО-13 Витрачання матеріалів'),
    ('mo_14', 'МО-14 Нарахування доходів спецфонду'),
    ('mo_15', 'МО-15 Розрахунки з батьками'),
    ('mo_16', 'МО-16 Позабалансовий облік'),
    ('mo_17', 'МО-17 Інші операції'),
]


# Mapping MO → set of (account_type, fund_filter, side). 'side' = which side of
# the move line interests us: 'debit' or 'credit'. Empty fund means both.
MO_ACCOUNT_FILTER = {
    'mo_1':  {'account_types': ('asset_cash',),         'codes': ('2411', '2412')},
    'mo_2':  {'account_types': ('asset_cash',),         'codes': ('2313',), 'fund': 'general'},
    'mo_3':  {'account_types': ('asset_cash',),         'codes': ('2313',), 'fund': 'special'},
    'mo_4':  {'account_types': ('asset_cash',),         'codes': ('2314',)},
    'mo_5':  {'account_types': ('liability_current',),  'codes': ('6511', '6512', '6513', '6514')},
    'mo_6':  {'account_types': ('liability_payable',),  'codes': ('6211',)},
    'mo_7':  {'account_types': ('asset_receivable',),   'codes': ('2113',)},
    'mo_8':  {'account_types': ('liability_current',),  'codes': ('6611', '6612', '6613')},
    'mo_9':  {'account_types': ('asset_non_current',),  'codes_prefix': ('10', '11', '12')},
    'mo_10': {'account_types': ('asset_non_current',),  'codes_prefix': ('11', '1812')},
    'mo_11': {'account_types': ('asset_current',),      'codes_prefix': ('20', '2011'), 'side': 'debit'},
    'mo_12': {'account_types': ('asset_current',),      'codes_prefix': ('20',),         'side': 'credit'},
    'mo_13': {'account_types': ('asset_current',),      'codes_prefix': ('2015', '2014', '1812'), 'side': 'credit'},
    'mo_14': {'account_types': ('income', 'income_other'),  'codes_prefix': ('7',)},
    'mo_15': {'account_types': ('asset_receivable',),       'codes': ('2114', '2117')},
    'mo_17': {'account_types': ('asset_current', 'liability_current'), 'codes': ('6614',)},
}


class MemorialOrderWizard(models.TransientModel):
    _name = 'l10n_ua.budget.memorial_order.wizard'
    _description = 'Меморіальний ордер 1-17'

    mo_kind = fields.Selection(MO_CHOICES, required=True, default='mo_2')
    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    def action_print(self):
        self.ensure_one()
        data = {
            'wizard_id': self.id,
            'mo_kind': self.mo_kind,
            'mo_label': dict(self._fields['mo_kind'].selection).get(self.mo_kind),
            'date_from': fields.Date.to_string(self.date_from),
            'date_to': fields.Date.to_string(self.date_to),
            'company_id': self.company_id.id,
        }
        data['data'] = dict(data)
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        return report.report_action(self, data=data)

    def _get_report_data_mo_16(self):
        """MO-16 off-balance report: Section 1 = positional register (matches OSV Class 0),
        Section 2 = chronological documents, Section 3 = historical AML."""
        company = self.company_id or self.env.company
        OBLine = self.env['l10n_ua.offbalance.move.line'].with_company(company)
        AML = self.env['account.move.line'].with_company(company)

        base_domain = [
            ('state', '=', 'posted'),
            ('company_id', '=', company.id),
        ]
        groupby = ['account_id']
        aggregates = ['debit:sum', 'credit:sum', 'quantity_in:sum', 'quantity_out:sum']

        # 1. Bucket map strictly by account_id to calculate positional balances in cut of subaccounts
        data = {}

        def get_bucket(acc_id):
            if acc_id not in data:
                data[acc_id] = {
                    'account_id': acc_id,
                    'opening_balance': 0.0,
                    'opening_qty': 0.0,
                    'turnover_debit': 0.0,
                    'turnover_credit': 0.0,
                    'quantity_in': 0.0,
                    'quantity_out': 0.0,
                }
            return data[acc_id]

        # Prior period: date < date_from
        open_rows = OBLine._read_group(
            base_domain + [('date', '<', self.date_from)],
            groupby,
            aggregates
        )
        for row in open_rows:
            acc_rec, d, c, qi, qo = row
            b = get_bucket(acc_rec.id)
            b['opening_balance'] += (d or 0.0) - (c or 0.0)
            b['opening_qty'] += (qi or 0.0) - (qo or 0.0)

        # Current period: date_from <= date <= date_to
        period_rows = OBLine._read_group(
            base_domain + [('date', '>=', self.date_from), ('date', '<=', self.date_to)],
            groupby,
            aggregates
        )
        for row in period_rows:
            acc_rec, d, c, qi, qo = row
            b = get_bucket(acc_rec.id)
            b['turnover_debit'] += (d or 0.0)
            b['turnover_credit'] += (c or 0.0)
            b['quantity_in'] += (qi or 0.0)
            b['quantity_out'] += (qo or 0.0)

        # Build positional list for subaccounts table
        Account = self.env['account.account'].with_company(company)
        acc_ids = list(data.keys())
        accounts = {a.id: a for a in Account.browse(acc_ids)}

        positions = []
        tot_open_bal = tot_open_qty = 0.0
        tot_turn_d = tot_turn_c = 0.0
        tot_turn_qi = tot_turn_qo = 0.0
        tot_close_bal = tot_close_qty = 0.0

        for acc_id, val in data.items():
            acc = accounts.get(acc_id)
            close_bal = val['opening_balance'] + val['turnover_debit'] - val['turnover_credit']
            close_qty = val['opening_qty'] + val['quantity_in'] - val['quantity_out']

            # Skip position only if completely empty across all periods
            if (company.currency_id.is_zero(val['opening_balance'])
                    and company.currency_id.is_zero(val['turnover_debit'])
                    and company.currency_id.is_zero(val['turnover_credit'])
                    and not val['opening_qty']
                    and not val['quantity_in']
                    and not val['quantity_out']):
                continue

            pos_data = {
                'account_id': acc_id,
                'account_code': acc.code if acc else '',
                'account_name': acc.name if acc else '',
                'opening_balance': val['opening_balance'],
                'opening_qty': val['opening_qty'],
                'sum_debit': val['turnover_debit'],
                'sum_credit': val['turnover_credit'],
                'sum_qty_in': val['quantity_in'],
                'sum_qty_out': val['quantity_out'],
                'closing_balance': close_bal,
                'closing_qty': close_qty,
            }
            positions.append(pos_data)

            tot_open_bal += val['opening_balance']
            tot_open_qty += val['opening_qty']
            tot_turn_d += val['turnover_debit']
            tot_turn_c += val['turnover_credit']
            tot_turn_qi += val['quantity_in']
            tot_turn_qo += val['quantity_out']
            tot_close_bal += close_bal
            tot_close_qty += close_qty

        positions.sort(key=lambda p: p['account_code'] or '')

        # 2. Chronological movements for typical form No. 16-avt (6-column table)
        ob_domain = base_domain + [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        ob_lines = OBLine.search(ob_domain, order='date, id')

        rows_mo16 = []
        credit_subtotals_map = defaultdict(float)
        debit_subtotals_map = defaultdict(float)
        account_names = {}

        for idx, ln in enumerate(ob_lines, 1):
            account_names[ln.account_id.code] = ln.account_id.name
            obj_name = ln.name or ''
            if ln.partner_id:
                obj_name = f"{obj_name} ({ln.partner_id.name})"

            if ln.direction == 'debit':
                doc = ln.move_id.ref or ln.move_id.name or ''
                if ln.date:
                    doc = f"{doc} від {ln.date}" if doc else str(ln.date)
                if ln.quantity_in:
                    qty_str = '{:,.2f}'.format(ln.quantity_in).replace(',', ' ')
                    doc = f"{doc} (к-сть: {qty_str})"
                cr_acc = '—'
                db_acc = ln.account_id.code or '—'
                debit_subtotals_map[ln.account_id.code] += ln.amount
            else:
                doc = ln.move_id.ref or ln.move_id.name or '—'
                if ln.date and doc != '—':
                    doc = f"{doc} від {ln.date}"
                if ln.quantity_out:
                    qty_str = '{:,.2f}'.format(ln.quantity_out).replace(',', ' ')
                    doc = f"{doc} (к-сть: {qty_str})"
                cr_acc = ln.account_id.code or '—'
                db_acc = '—'
                credit_subtotals_map[ln.account_id.code] += ln.amount

            rows_mo16.append({
                'num': idx,
                'object_name': obj_name,
                'receipt_doc': doc,
                'credit_account': cr_acc,
                'debit_account': db_acc,
                'amount': ln.amount,
                'date': ln.date,
                'move_name': ln.move_id.name if not ln.move_id.ref else f"{ln.move_id.name} ({ln.move_id.ref})",
                'account_code': ln.account_id.code,
                'account_name': ln.account_id.name,
                'description': ln.name or '',
                'partner': ln.partner_id.name if ln.partner_id else '',
                'quantity': ln.quantity_in if ln.direction == 'debit' else ln.quantity_out,
                'debit': ln.debit,
                'credit': ln.credit,
                'source': 'register',
                'source_label': 'Регістр',
            })

        credit_subtotals = [
            {'code': code, 'name': account_names.get(code, ''), 'amount': amt}
            for code, amt in sorted(credit_subtotals_map.items())
        ]
        debit_subtotals = [
            {'code': code, 'name': account_names.get(code, ''), 'amount': amt}
            for code, amt in sorted(debit_subtotals_map.items())
        ]
        total_credit = sum(item['amount'] for item in credit_subtotals)
        total_debit = sum(item['amount'] for item in debit_subtotals)
        total_turnover = total_debit + total_credit

        # 3. Historical account.move.line entries for off-balance accounts
        all_curr_aml = AML.search([
            ('parent_state', '=', 'posted'),
            ('company_id', '=', company.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('account_id.account_type', '=', 'off_balance'),
        ], order='date, id')
        # Hide 09* only when the same move also has non-09 off-balance lines (technical contra)
        moves_with_non_09 = {
            ln.move_id.id for ln in all_curr_aml
            if not (ln.account_id.code or '').startswith('09')
        }
        rows_historical = []
        sum_hist_d = sum_hist_c = 0.0
        for ln in all_curr_aml:
            acc_code = ln.account_id.code or ''
            if ln.move_id.id in moves_with_non_09 and acc_code.startswith('09'):
                continue
            move_name = ln.move_id.name
            if ln.move_id.ref:
                move_name = f"{move_name} ({ln.move_id.ref})"
            rows_historical.append({
                'date': ln.date,
                'move_name': move_name,
                'source': 'historical',
                'source_label': 'Історичні',
                'account_code': acc_code,
                'account_name': ln.account_id.name,
                'description': ln.name or '',
                'partner': ln.partner_id.name if ln.partner_id else '',
                'quantity': ln.quantity or 0.0,
                'debit': ln.debit,
                'credit': ln.credit,
            })
            sum_hist_d += ln.debit
            sum_hist_c += ln.credit

        sort_key = lambda r: (fields.Date.to_date(r['date']) or fields.Date.today(), r['move_name'] or '')
        rows_historical.sort(key=sort_key)

        # 4. Check historical unreversed balances in account.move.line prior to date_from
        hist_open_rows = AML._read_group(
            [
                ('parent_state', '=', 'posted'),
                ('company_id', '=', company.id),
                ('date', '<', self.date_from),
                ('account_id.account_type', '=', 'off_balance'),
            ],
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum'],
        )
        prior_bal_by_acc = {}
        hist_prior_balance = 0.0
        for acc, d, c in hist_open_rows:
            bal = (d or 0.0) - (c or 0.0)
            prior_bal_by_acc[acc.id] = bal
            if company.currency_id.compare_amounts(bal, 0.0) > 0:
                hist_prior_balance += bal
        has_prior_unreversed = company.currency_id.compare_amounts(hist_prior_balance, 0.0) > 0

        has_unmigrated_prior_balance = (
            has_prior_unreversed and company.currency_id.is_zero(tot_open_bal)
        )
        has_unreversed_prior_balance = (
            has_prior_unreversed and not company.currency_id.is_zero(tot_open_bal)
        )

        # 5. Active current-period AML entries excluding standard reversals and entries reversed in-period
        active_curr_aml = all_curr_aml.filtered(
            lambda l: not l.move_id.reversed_entry_id
            and not any(
                rev.state == 'posted' and self.date_from <= rev.date <= self.date_to
                for rev in l.move_id.reversal_move_ids
            )
        )
        manual_prior_close_only = False
        if active_curr_aml:
            curr_delta_by_acc = defaultdict(float)
            for ln in active_curr_aml:
                curr_delta_by_acc[ln.account_id.id] += (ln.debit or 0.0) - (ln.credit or 0.0)
            manual_prior_close_only = all(
                not company.currency_id.is_zero(prior_bal_by_acc.get(acc_id, 0.0))
                and company.currency_id.is_zero(prior_bal_by_acc.get(acc_id, 0.0) + delta)
                for acc_id, delta in curr_delta_by_acc.items()
            )

        is_register_empty = bool(not rows_mo16 and not positions)
        has_unmigrated_historical = bool(active_curr_aml) and not manual_prior_close_only

        return {
            'positions': positions,
            'rows_mo16': rows_mo16,
            'rows_register': rows_mo16,
            'rows_historical': rows_historical,
            'rows': rows_mo16,
            'credit_subtotals': credit_subtotals,
            'debit_subtotals': debit_subtotals,
            'total_credit': total_credit,
            'total_debit': total_debit,
            'total_turnover': total_turnover,
            'opening_balance': tot_open_bal,
            'opening_qty': tot_open_qty,
            'sum_debit': tot_turn_d,
            'sum_credit': tot_turn_c,
            'sum_qty_in': tot_turn_qi,
            'sum_qty_out': tot_turn_qo,
            'closing_balance': tot_close_bal,
            'closing_qty': tot_close_qty,
            'sum_register_debit': tot_turn_d,
            'sum_register_credit': tot_turn_c,
            'sum_historical_debit': sum_hist_d,
            'sum_historical_credit': sum_hist_c,
            'has_historical': bool(rows_historical),
            'is_register_empty': is_register_empty,
            'has_unmigrated_historical': has_unmigrated_historical,
            'hist_prior_balance': hist_prior_balance,
            'has_unmigrated_prior_balance': has_unmigrated_prior_balance,
            'has_unreversed_prior_balance': has_unreversed_prior_balance,
        }

    def get_report_data(self):
        """Aggregate posted journal lines per MO definition."""
        self.ensure_one()
        if self.mo_kind == 'mo_16':
            return self._get_report_data_mo_16()
        spec = MO_ACCOUNT_FILTER.get(self.mo_kind, {})
        company = self.company_id or self.env.company
        AML = self.env['account.move.line'].with_company(company)
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', company.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        if spec.get('account_types'):
            domain.append(('account_id.account_type', 'in', list(spec['account_types'])))
        if spec.get('codes'):
            domain.append(('account_id.code', 'in', list(spec['codes'])))
        if spec.get('codes_prefix'):
            prefixes = spec['codes_prefix']
            prefix_domain = [('account_id.code', '=like', f'{p}%') for p in prefixes]
            if len(prefix_domain) > 1:
                # Build N-way OR: ['|'] * (N-1) + prefix_domain
                domain = domain + ['|'] * (len(prefix_domain) - 1) + prefix_domain
            else:
                domain = domain + prefix_domain
        if spec.get('fund'):
            domain.append(('ua_fund_type', '=', spec['fund']))

        lines = AML.search(domain, order='date, id')
        rows = []
        sum_d = sum_c = 0.0
        for ln in lines:
            rows.append({
                'date': ln.date,
                'move_name': ln.move_id.name,
                'account_code': ln.account_id.code,
                'account_name': ln.account_id.name,
                'description': ln.name or '',
                'partner': ln.partner_id.name if ln.partner_id else '',
                'debit': ln.debit,
                'credit': ln.credit,
            })
            sum_d += ln.debit
            sum_c += ln.credit
        return {
            'rows': rows,
            'sum_debit': sum_d,
            'sum_credit': sum_c,
        }
