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
    'mo_16': {'account_types': ('off_balance',),            'codes_prefix': ('0',)},
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
        }
        data['data'] = dict(data)
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        return report.report_action(self, data=data)

    def _get_report_data_mo_16(self):
        """MO-16 off-balance report: Section 1 = register (matches OSV Class 0), Section 2 = historical AML."""
        rows_register = []
        rows_historical = []
        sum_reg_d = sum_reg_c = 0.0
        sum_hist_d = sum_hist_c = 0.0

        # 1. New off-balance register (single-entry)
        ob_domain = [
            ('state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        ob_lines = self.env['l10n_ua.offbalance.move.line'].search(ob_domain, order='date, id')
        for ln in ob_lines:
            move_name = ln.move_id.name
            if ln.move_id.ref:
                move_name = f"{move_name} ({ln.move_id.ref})"
            qty = ln.quantity_in if ln.direction == 'debit' else ln.quantity_out
            rows_register.append({
                'date': ln.date,
                'move_name': move_name,
                'source': 'register',
                'source_label': 'Регістр',
                'account_code': ln.account_id.code,
                'account_name': ln.account_id.name,
                'description': ln.name or '',
                'partner': ln.partner_id.name if ln.partner_id else '',
                'quantity': qty,
                'debit': ln.debit,
                'credit': ln.credit,
            })
            sum_reg_d += ln.debit
            sum_reg_c += ln.credit

        # 2. Historical account.move.line entries for off-balance accounts (legacy double-entry)
        aml_domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('account_id.account_type', '=', 'off_balance'),
        ]
        aml_lines = self.env['account.move.line'].search(aml_domain, order='date, id')
        for ln in aml_lines:
            move_name = ln.move_id.name
            if ln.move_id.ref:
                move_name = f"{move_name} ({ln.move_id.ref})"
            rows_historical.append({
                'date': ln.date,
                'move_name': move_name,
                'source': 'historical',
                'source_label': 'Історичні',
                'account_code': ln.account_id.code,
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
        rows_register.sort(key=sort_key)
        rows_historical.sort(key=sort_key)

        return {
            'rows_register': rows_register,
            'rows_historical': rows_historical,
            'rows': rows_register + rows_historical,
            'sum_debit': sum_reg_d,
            'sum_credit': sum_reg_c,
            'sum_register_debit': sum_reg_d,
            'sum_register_credit': sum_reg_c,
            'sum_historical_debit': sum_hist_d,
            'sum_historical_credit': sum_hist_c,
            'has_historical': bool(rows_historical),
        }

    def get_report_data(self):
        """Aggregate posted journal lines per MO definition."""
        self.ensure_one()
        if self.mo_kind == 'mo_16':
            return self._get_report_data_mo_16()
        spec = MO_ACCOUNT_FILTER.get(self.mo_kind, {})
        AML = self.env['account.move.line']
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
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
