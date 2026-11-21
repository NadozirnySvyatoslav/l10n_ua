from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError


class AgroCostCalculation(models.Model):
    """Калькуляція собівартості продукції рослинництва за сезон.

    1. Прямі витрати — рядки рахунку 23 з посівом (наряди, оцінка врожаю за
       плановою собівартістю).
    2. Непрямі — рядки 23 без посіву (оренда землі, зарплата, амортизація) і,
       за бажанням, 91 — розподіляються між посівами пропорційно прямим
       витратам за період: Дт 23 (посів) — Кт 23 / 91.
    3. Посіви сезону, що закривається, закриваються: Дт 940 — Кт 23 (метод
       справедливої вартості) або Дт 27 — Кт 23 (доведення планової
       собівартості до фактичної). Посіви наступного сезону (озимі) лишаються
       на 23 як незавершене виробництво.
    """
    _name = 'l10n_ua.agro.cost.calculation'
    _description = 'Crop Cost Calculation'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(default='/', copy=False, readonly=True)
    season_id = fields.Many2one(
        'l10n_ua.agro.season', string='Season', required=True, tracking=True,
        domain="[('company_id', '=', company_id)]")
    date_from = fields.Date(string='Costs From', required=True, compute='_compute_dates', store=True, readonly=False, precompute=True)
    date = fields.Date(
        string='Closing Date', required=True, compute='_compute_dates', store=True, readonly=False,
        precompute=True,
        tracking=True, help='Дата закриття: витрати рахуються до неї включно, на неї ж проводка.')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    valuation_method = fields.Selection(related='company_id.l10n_ua_agro_valuation_method')
    include_overhead = fields.Boolean(
        string='Allocate Overhead (91)', default=True,
        help='Розподілити загальновиробничі витрати (91) за період на посіви.')
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self.env.company.l10n_ua_agro_operations_journal_id or self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1))
    line_ids = fields.One2many('l10n_ua.agro.cost.calculation.line', 'calculation_id', string='Plantings', copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    indirect_amount = fields.Monetary(string='Indirect Costs (23)', readonly=True, copy=False)
    overhead_amount = fields.Monetary(string='Overhead (91)', readonly=True, copy=False)
    total_cost = fields.Monetary(string='Season Cost', compute='_compute_totals')
    closing_amount = fields.Monetary(string='Closed from 23', compute='_compute_totals')
    note = fields.Text()

    @api.depends('season_id')
    def _compute_dates(self):
        for calc in self:
            if calc.season_id:
                calc.date_from = calc.season_id.date_start
                calc.date = calc.season_id.date_end

    @api.depends('line_ids.total_cost', 'line_ids.closing_amount', 'line_ids.is_wip')
    def _compute_totals(self):
        for calc in self:
            season = calc.line_ids.filtered(lambda l: not l.is_wip)
            calc.total_cost = sum(season.mapped('total_cost'))
            calc.closing_amount = sum(season.mapped('closing_amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'l10n_ua.agro.cost.calculation') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(calc.state == 'posted' for calc in self):
            raise UserError(self.env._('Cancel the posted calculation before deleting it.'))
        return super().unlink()

    # --- Розрахунок ---

    def _production_account(self):
        return self.company_id._l10n_ua_agro_ops_account('l10n_ua_agro_production_account_id', ('231', '23'))

    def _overhead_account(self):
        return self.company_id._l10n_ua_agro_ops_account('l10n_ua_agro_overhead_account_id', ('91',))

    def _base_domain(self, account):
        return [
            ('account_id', '=', account.id),
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date),
            # проводки інших калькуляцій уже розподілені / закриті
            ('move_id.l10n_ua_agro_calculation_id', '=', False),
        ]

    def action_compute(self):
        AML = self.env['account.move.line']
        for calc in self:
            if calc.state != 'draft':
                raise UserError(self.env._('Only a draft calculation can be recomputed.'))
            account = calc._production_account()
            if not account:
                raise UserError(self.env._('Set the crop production account in the Agro settings.'))
            calc.line_ids.unlink()
            # Оцінка врожаю за плановою собівартістю (і її сторно) — це вже
            # списання з 23, а не витрати; решта рядків з посівом — витрати
            # (сторно скасованих нарядів зменшує їх).
            harvest_moves = self.env['l10n_ua.agro.harvest.receipt'].search([
                ('company_id', '=', calc.company_id.id), ('account_move_id', '!=', False),
            ]).account_move_id
            harvest_moves |= harvest_moves.reversal_move_ids
            direct = defaultdict(float)
            credits = defaultdict(float)
            for planting, move, balance in AML._read_group(
                    calc._base_domain(account) + [('l10n_ua_agro_planting_id', '!=', False)],
                    ['l10n_ua_agro_planting_id', 'move_id'], ['balance:sum']):
                if move in harvest_moves:
                    credits[planting] -= balance
                else:
                    direct[planting] += balance
            indirect = sum(AML.search(calc._base_domain(account) + [
                ('l10n_ua_agro_planting_id', '=', False)]).mapped('balance'))
            overhead = 0.0
            overhead_account = calc._overhead_account()
            if calc.include_overhead and overhead_account:
                overhead = sum(AML.search(calc._base_domain(overhead_account)).mapped('balance'))
            season_plantings = self.env['l10n_ua.agro.planting'].search([
                ('season_id', '=', calc.season_id.id), ('company_id', '=', calc.company_id.id)])
            plantings = season_plantings | self.env['l10n_ua.agro.planting'].browse(
                [p.id for p in direct])
            base_total = sum(direct.values())
            currency = calc.currency_id
            lines = []
            shares = {}
            for planting in plantings:
                share = direct.get(planting, 0.0) / base_total if base_total else 0.0
                shares[planting] = share
            # розподіл без копійчаних хвостів: залишок — на найбільший посів
            allocated = {p: currency.round(indirect * s) for p, s in shares.items()}
            allocated_oh = {p: currency.round(overhead * s) for p, s in shares.items()}
            if plantings and base_total:
                biggest = max(plantings, key=lambda p: direct.get(p, 0.0))
                allocated[biggest] += currency.round(indirect - sum(allocated.values()))
                allocated_oh[biggest] += currency.round(overhead - sum(allocated_oh.values()))
            for planting in plantings:
                lines.append({
                    'calculation_id': calc.id,
                    'planting_id': planting.id,
                    'is_wip': planting.season_id != calc.season_id,
                    'direct_cost': direct.get(planting, 0.0),
                    'allocated_cost': allocated.get(planting, 0.0),
                    'overhead_cost': allocated_oh.get(planting, 0.0),
                    'credited_amount': credits.get(planting, 0.0),
                })
            self.env['l10n_ua.agro.cost.calculation.line'].create(lines)
            calc.write({'indirect_amount': indirect, 'overhead_amount': overhead})
        return True

    # --- Проведення ---

    def action_post(self):
        for calc in self:
            if calc.state != 'draft':
                continue
            if not calc.line_ids:
                raise UserError(self.env._('Compute the calculation first.'))
            adjustments = calc._harvest_adjustments()
            move = self.env['account.move'].create(calc._prepare_move_vals(adjustments))
            move.action_post()
            calc.write({'move_id': move.id, 'state': 'posted'})
            calc._apply_harvest_adjustments(adjustments)
        return True

    def _harvest_receipts(self, planting):
        """Оприбуткування посіву, вже списані з 23 за плановою собівартістю."""
        return self.env['l10n_ua.agro.harvest.receipt'].search([
            ('planting_id', '=', planting.id), ('company_id', '=', self.company_id.id),
            ('state', '=', 'done'), ('account_move_id.state', '=', 'posted'),
            ('account_move_id.date', '>=', self.date_from), ('account_move_id.date', '<=', self.date),
        ], order='date, id')

    def _harvest_adjustments(self):
        """Метод планової собівартості: різниця до фактичної (Дт 27 — Кт 23)
        розноситься на оприбуткування посіву пропорційно їх оцінці — так само
        змінюється й вартість продукції на складі (#603).
        Повертає {посів: [(оприбуткування, сума), …]}."""
        self.ensure_one()
        result = {}
        if self.valuation_method == 'fair_value':
            return result
        currency = self.currency_id
        for calc_line in self.line_ids.filtered(lambda l: not l.is_wip):
            amount = calc_line.closing_amount
            receipts = self._harvest_receipts(calc_line.planting_id)
            base = sum(receipts.mapped('valuation_amount'))
            if currency.is_zero(amount) or not receipts or currency.is_zero(base):
                continue
            parts = [(r, currency.round(amount * r.valuation_amount / base)) for r in receipts]
            # копійчаний залишок — на найбільше оприбуткування
            biggest = max(range(len(parts)), key=lambda i: parts[i][0].valuation_amount)
            receipt, part = parts[biggest]
            parts[biggest] = (receipt, part + currency.round(amount - sum(p for _r, p in parts)))
            result[calc_line.planting_id] = parts
        return result

    def _apply_harvest_adjustments(self, adjustments):
        receipts = self.env['l10n_ua.agro.harvest.receipt']
        for parts in adjustments.values():
            for receipt, amount in parts:
                receipt.write({'cost_adjustment': amount, 'cost_calculation_id': self.id})
                receipts |= receipt
        receipts._revalue_stock()

    def _prepare_move_vals(self, adjustments=None):
        self.ensure_one()
        adjustments = adjustments or {}
        company = self.company_id
        currency = self.currency_id
        production = self._production_account()
        lines = []

        def line(account, amount, name, planting=None):
            if currency.is_zero(amount):
                return
            vals = {'name': name, 'account_id': account.id,
                    'debit': amount if amount > 0 else 0.0, 'credit': -amount if amount < 0 else 0.0}
            if planting:
                vals['l10n_ua_agro_planting_id'] = planting.id
                vals['analytic_distribution'] = {'%s,%s' % (
                    planting.field_id._l10n_ua_agro_analytic_account().id,
                    planting.crop_id._l10n_ua_agro_analytic_account(company).id): 100.0}
            lines.append((0, 0, vals))

        for calc_line in self.line_ids:
            planting = calc_line.planting_id
            line(production, calc_line.allocated_cost,
                 self.env._('Indirect costs to %s', planting.display_name), planting)
            line(production, calc_line.overhead_cost,
                 self.env._('Production overhead to %s', planting.display_name), planting)
        line(production, -self.indirect_amount, self.env._('Indirect costs allocated to plantings'))
        if self.overhead_amount:
            line(self._overhead_account(), -self.overhead_amount,
                 self.env._('Production overhead allocated to plantings'))

        if self.valuation_method == 'fair_value':
            target = company._l10n_ua_agro_ops_account('l10n_ua_agro_recognition_expense_account_id', ('940',))
        else:
            target = company._l10n_ua_agro_ops_account('l10n_ua_agro_produce_account_id', ('27',))
        if not target:
            raise UserError(self.env._('Set the accounts of the harvest valuation in the Agro settings.'))
        for calc_line in self.line_ids.filtered(lambda l: not l.is_wip):
            planting = calc_line.planting_id
            name = self.env._('Cost of %(planting)s, %(season)s',
                              planting=planting.display_name, season=self.season_id.name)
            line(production, -calc_line.closing_amount, name, planting)
            parts = adjustments.get(planting)
            if parts:
                # на рахунок оцінки продукції кожного оприбуткування
                for receipt, amount in parts:
                    line(receipt._produce_account(), amount, name)
            else:
                line(target, calc_line.closing_amount, name)
        return {
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.name,
            'company_id': company.id,
            'l10n_ua_agro_calculation_id': self.id,
            'line_ids': lines,
        }

    def action_cancel(self):
        receipts = self.env['l10n_ua.agro.harvest.receipt'].search([('cost_calculation_id', 'in', self.ids)])
        receipts.write({'cost_adjustment': 0.0, 'cost_calculation_id': False})
        receipts._revalue_stock()
        for calc in self:
            if calc.move_id:
                calc.move_id._reverse_moves(
                    [{'date': calc.move_id.date, 'ref': self.env._('Reversal of %s', calc.name),
                      'l10n_ua_agro_calculation_id': calc.id}], cancel=True)
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda c: c.state == 'cancel').write({'state': 'draft', 'move_id': False})

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }


class AgroCostCalculationLine(models.Model):
    _name = 'l10n_ua.agro.cost.calculation.line'
    _description = 'Crop Cost Calculation Line'
    _order = 'calculation_id, is_wip, crop_id, field_id'

    calculation_id = fields.Many2one(
        'l10n_ua.agro.cost.calculation', required=True, ondelete='cascade', index=True)
    state = fields.Selection(related='calculation_id.state', store=True)
    company_id = fields.Many2one(related='calculation_id.company_id', store=True)
    currency_id = fields.Many2one(related='calculation_id.currency_id')
    planting_id = fields.Many2one('l10n_ua.agro.planting', string='Planting', required=True)
    field_id = fields.Many2one(related='planting_id.field_id', store=True)
    crop_id = fields.Many2one(related='planting_id.crop_id', store=True)
    season_id = fields.Many2one(related='planting_id.season_id', store=True)
    area = fields.Float(related='planting_id.area', string='Area (ha)')
    is_wip = fields.Boolean(
        string='Work in Progress',
        help='Посів наступного сезону (напр. озимі): витрати лишаються на 23 як незавершене виробництво.')
    direct_cost = fields.Monetary(string='Direct Costs')
    allocated_cost = fields.Monetary(string='Indirect Costs')
    overhead_cost = fields.Monetary(string='Overhead')
    total_cost = fields.Monetary(string='Total Cost', compute='_compute_amounts', store=True)
    credited_amount = fields.Monetary(
        string='Already Credited',
        help='Уже списано з 23 при оприбуткуванні врожаю за плановою собівартістю.')
    closing_amount = fields.Monetary(string='Closed from 23', compute='_compute_amounts', store=True)
    harvest_weight = fields.Float(related='planting_id.harvest_weight', string='Harvested (t)')
    cost_per_ton = fields.Monetary(string='Cost per t', compute='_compute_amounts', store=True)
    cost_per_ha = fields.Monetary(string='Cost per ha', compute='_compute_amounts', store=True)

    @api.depends('direct_cost', 'allocated_cost', 'overhead_cost', 'credited_amount', 'is_wip',
                 'planting_id.harvest_weight', 'planting_id.area')
    def _compute_amounts(self):
        for line in self:
            line.total_cost = line.direct_cost + line.allocated_cost + line.overhead_cost
            line.closing_amount = 0.0 if line.is_wip else line.total_cost - line.credited_amount
            weight = line.planting_id.harvest_weight
            line.cost_per_ton = line.total_cost / weight if weight and not line.is_wip else 0.0
            line.cost_per_ha = line.total_cost / line.planting_id.area if line.planting_id.area else 0.0
