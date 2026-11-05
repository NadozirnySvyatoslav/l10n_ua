"""Статті бюджету (довідник) для комерційного бюджетування.

Стаття визначає, які проводки рахуються фактом:

* БДР (бюджет доходів і витрат, метод нарахування) — обороти за рахунками
  статті: дохід = кредитове сальдо, витрата = дебетове сальдо;
* БДДС (бюджет руху грошових коштів, касовий метод) — як у прямому методі
  Ф№3: беруться проводки з грошовим боком (каса, банк, рахунки «в дорозі»),
  а стаття визначається **кореспондуючим** рахунком. Надходження — кредит
  контр-рахунку (Дт 311 Кт 361), видаток — дебет (Дт 631 Кт 311).

Рахунки задаються явно (``account_ids``) та/або префіксами кодів
(``account_codes``: «70, 71»). Префікси переносні між компаніями, бо в кожної
компанії свій екземпляр плану рахунків.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class L10nUaBudgetItem(models.Model):
    _name = 'l10n_ua.budget.item'
    _description = 'Budget Item'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'budget_type, sequence, code, name'
    _rec_names_search = ['code', 'name']

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one(
        'l10n_ua.budget.item', string='Parent Item', index=True, ondelete='restrict',
        domain="[('budget_type', '=', budget_type)]",
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('l10n_ua.budget.item', 'parent_id', string='Sub-items')
    budget_type = fields.Selection(
        [('pnl', 'Income & Expense Budget (accrual)'),
         ('cash', 'Cash Flow Budget (cash basis)')],
        string='Budget Type', required=True, default='pnl',
        help='Income & Expense Budget (БДР): actuals are account balances of the '
             'item accounts.\nCash Flow Budget (БДДС): actuals are cash and bank '
             'movements whose counterpart account belongs to the item.',
    )
    item_type = fields.Selection(
        [('income', 'Income / Inflow'), ('expense', 'Expense / Outflow')],
        string='Direction', required=True, default='expense',
    )
    account_ids = fields.Many2many(
        'account.account', 'l10n_ua_budget_item_account_rel', 'item_id', 'account_id',
        string='Accounts',
        help='Accounts whose movements make the actual of this item. For a cash '
             'flow item these are counterpart accounts of cash movements.',
    )
    account_codes = fields.Char(
        string='Account Code Prefixes',
        help='Comma-separated account code prefixes, e.g. "70, 71". Combined '
             'with the explicit accounts. Prefixes work for every company.',
    )
    analytic_account_ids = fields.Many2many(
        'account.analytic.account', 'l10n_ua_budget_item_analytic_rel', 'item_id', 'analytic_id',
        string='Analytic Accounts',
        help='Optional: only journal items distributed to these analytic '
             'accounts count as actual of the item.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        help='Leave empty to share the item between companies.',
    )
    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, budget_type, company_id)',
        'Budget item code must be unique per budget type and company!',
    )

    @api.constrains('parent_id')
    def _check_parent(self):
        if self._has_cycle():
            raise ValidationError(_('Budget items cannot be nested recursively.'))
        for item in self:
            if item.parent_id and item.parent_id.budget_type != item.budget_type:
                raise ValidationError(_(
                    'Item "%(item)s" and its parent must have the same budget type.',
                    item=item.display_name))

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for item in self:
            item.display_name = f'[{item.code}] {item.name}' if item.code else item.name

    def _get_code_prefixes(self):
        self.ensure_one()
        return [p.strip() for p in (self.account_codes or '').replace(';', ',').split(',') if p.strip()]

    def _get_accounts(self, company):
        """Рахунки статті та її підстатей для компанії."""
        Account = self.env['account.account'].with_company(company)
        accounts = Account.browse()
        for item in self.search([('id', 'child_of', self.ids)]):
            accounts |= item.account_ids.filtered(lambda a: company in a.company_ids)
            for prefix in item._get_code_prefixes():
                accounts |= Account.search([
                    ('code', '=like', f'{prefix}%'),
                    ('company_ids', 'in', company.id),
                ])
        return accounts

    def _get_analytic_filter(self):
        """Аналітичні рахунки фільтра статті (з підстатями)."""
        return self.search([('id', 'child_of', self.ids)]).analytic_account_ids
