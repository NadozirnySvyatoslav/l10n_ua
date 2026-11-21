from odoo import fields, models
from odoo.exceptions import UserError


class AgroHarvestReceipt(models.Model):
    """Первісне визнання сільгосппродукції (П(С)БО 30) при оприбуткуванні:
    Дт 27 — Кт 710 за справедливою вартістю або Дт 27 — Кт 23 за плановою
    собівартістю з техкарти."""
    _inherit = 'l10n_ua.agro.harvest.receipt'

    currency_id = fields.Many2one(related='company_id.currency_id')
    valuation_price = fields.Float(
        string='Valuation Price per kg', digits=(12, 4), readonly=True, copy=False,
        help='Справедлива вартість мінус витрати на місці продажу або планова собівартість, грн/кг.')
    valuation_amount = fields.Monetary(string='Valuation', readonly=True, copy=False)
    account_move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    cost_calculation_id = fields.Many2one(
        'l10n_ua.agro.cost.calculation', string='Cost Calculation', readonly=True, copy=False,
        index='btree_not_null')
    cost_adjustment = fields.Monetary(
        string='Cost Adjustment', readonly=True, copy=False,
        help='Доведення планової собівартості до фактичної калькуляцією сезону — '
             'частка цього оприбуткування; змінює й вартість на складі.')

    def action_done(self):
        drafts = self.filtered(lambda r: r.state == 'draft')
        # оцінка — до проведення руху: склад бере з неї вартість вхідного руху
        drafts.filtered(lambda r: r.product_id and r.credit_weight > 0)._compute_valuation()
        res = super().action_done()
        drafts.filtered(lambda r: r.state == 'done')._post_valuation()
        return res

    def _l10n_ua_agro_stock_value(self):
        """Вартість оприбуткування на складі — та сама, що на рахунку 27."""
        self.ensure_one()
        return self.valuation_amount + self.cost_adjustment

    def _compute_valuation(self):
        for receipt in self:
            receipt._check_cost_method()
            price = receipt._valuation_price()
            amount = receipt.company_id.currency_id.round(price * receipt.credit_weight)
            receipt.write({'valuation_price': price, 'valuation_amount': amount, 'cost_adjustment': 0.0})

    def _check_cost_method(self):
        """За стандартною ціною склад оцінює залишок як ціна товару × кількість,
        а не за оприбуткуваннями — оцінка врожаю на склад не потрапить, і закриття
        складу зніме її з рахунку 27."""
        self.ensure_one()
        product = self.product_id.with_company(self.company_id)
        if product.is_storable and product.cost_method == 'standard':
            raise UserError(self.env._(
                '%(product)s is costed at the standard price (category: %(category)s). The harvest '
                'is valued under P(S)BO 30 by every receipt, so give the product a category with the '
                'AVCO or FIFO costing method (Inventory → Configuration → Product Categories): '
                'otherwise the stock value and account 27 diverge.',
                product=product.display_name,
                category=product.categ_id.display_name or self.env._('none')))

    def _produce_account(self):
        """Рахунок оцінки запасів з категорії товару — той, який звіряє закриття
        складу; без нього — рахунок продукції з налаштувань агро (27)."""
        self.ensure_one()
        company = self.company_id
        return self.product_id.categ_id.with_company(company).property_stock_valuation_account_id \
            or company._l10n_ua_agro_ops_account('l10n_ua_agro_produce_account_id', ('27',))

    def _valuation_price(self):
        """Ціна 1 кг: справедлива вартість (за одиницю товару → за кг) або
        планова собівартість кілограма з техкарти."""
        self.ensure_one()
        company = self.company_id
        if company.l10n_ua_agro_valuation_method == 'fair_value':
            price = self.env['l10n_ua.agro.fair.value']._get_price(
                self.product_id, fields.Date.to_date(self.date), company)
            if price is None:
                raise UserError(self.env._(
                    'Set the fair value of %(product)s on %(date)s (Agro → Configuration → Fair Values).',
                    product=self.product_id.display_name, date=fields.Date.to_date(self.date)))
            kg = self.env.ref('uom.product_uom_kgm')
            # ціна за одиницю товару → за кг
            return kg._compute_price(price, self.product_id.uom_id)
        card = self.env['l10n_ua.agro.tech.card'].search([
            ('crop_id', '=', self.crop_id.id), ('season_id', '=', self.season_id.id),
            ('company_id', '=', company.id)], limit=1)
        if not card.planned_unit_cost:
            raise UserError(self.env._(
                'Set the planned yield in the technological card of %(crop)s for %(season)s: '
                'the harvest is valued at the planned cost.',
                crop=self.crop_id.name, season=self.season_id.name))
        return card.planned_unit_cost

    def _post_valuation(self):
        for receipt in self:
            company = receipt.company_id
            amount = receipt.valuation_amount
            if company.currency_id.is_zero(amount):
                continue
            produce = receipt._produce_account()
            if company.l10n_ua_agro_valuation_method == 'fair_value':
                credit = company._l10n_ua_agro_ops_account(
                    'l10n_ua_agro_recognition_income_account_id', ('710',))
                credit_vals = {}
            else:
                credit = company._l10n_ua_agro_ops_account(
                    'l10n_ua_agro_production_account_id', ('231', '23'))
                credit_vals = {
                    'l10n_ua_agro_planting_id': receipt.planting_id.id,
                    'analytic_distribution': receipt._agro_analytic_distribution(),
                }
            if not produce or not credit:
                raise UserError(self.env._('Set the accounts of the harvest valuation in the Agro settings.'))
            journal = company.l10n_ua_agro_operations_journal_id or self.env['account.journal'].search([
                ('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
            label = self.env._('Harvest %(receipt)s: %(product)s, %(weight)s kg',
                               receipt=receipt.name, product=receipt.product_id.display_name,
                               weight=receipt.credit_weight)
            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.to_date(receipt.date),
                'ref': receipt.name,
                'company_id': company.id,
                'line_ids': [
                    (0, 0, {'name': label, 'account_id': produce.id, 'debit': amount,
                            'analytic_distribution': receipt._agro_analytic_distribution()}),
                    (0, 0, dict({'name': label, 'account_id': credit.id, 'credit': amount}, **credit_vals)),
                ],
            })
            move.action_post()
            receipt.account_move_id = move

    def _agro_analytic_distribution(self):
        self.ensure_one()
        field_account = self.field_id._l10n_ua_agro_analytic_account()
        crop_account = self.crop_id._l10n_ua_agro_analytic_account(self.company_id)
        return {'%s,%s' % (field_account.id, crop_account.id): 100.0}

    def action_cancel(self):
        for receipt in self.filtered(lambda r: r.state == 'done' and r.account_move_id):
            if receipt.account_move_id.l10n_ua_agro_calculation_id:
                continue
            calc = self.env['l10n_ua.agro.cost.calculation'].search([
                ('season_id', '=', receipt.season_id.id), ('state', '=', 'posted'),
                ('company_id', '=', receipt.company_id.id)], limit=1)
            if calc:
                raise UserError(self.env._(
                    'The cost of %(season)s is already calculated (%(calc)s): cancel the calculation first.',
                    season=receipt.season_id.name, calc=calc.name))
        res = super().action_cancel()
        for receipt in self.filtered('account_move_id'):
            receipt.account_move_id.sudo()._reverse_moves(
                [{'date': receipt.account_move_id.date,
                  'ref': self.env._('Reversal of %s', receipt.name)}], cancel=True)
        return res

    def action_draft(self):
        res = super().action_draft()
        self.write({'account_move_id': False, 'valuation_price': 0.0, 'valuation_amount': 0.0,
                    'cost_adjustment': 0.0, 'cost_calculation_id': False})
        return res

    def _revalue_stock(self):
        """Перерахувати вартість вхідних рухів після доведення собівартості."""
        moves = self.move_id.filtered(lambda m: m.state == 'done')
        if moves:
            moves.sudo()._set_value()
