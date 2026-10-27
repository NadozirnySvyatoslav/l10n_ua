"""Додаток 4 (Д4, J0299326 / F0299326): пільги, підприємства осіб з інвалідністю, п. 68.

Форма — наказ Мінфіну № 21 у редакції № 400; Порядок заповнення — розд. V п. 3
пп. 6 (рядки 5/5.1) і розд. V-1 (у консолідованому тексті Порядку додаток ще має
старий номер Д5). Д4 обов'язковий, якщо заповнено рядок 5 декларації, а також для
підприємств осіб з інвалідністю і платників за п. 68 підрозд. 10 розд. XX ПКУ.

* Таблиця 1 — операції, що не є об'єктом оподаткування (T11), і послуги за межами
  митної території / з місцем постачання за п. 186.2, 186.3 (T12). Заповнюється
  вручну; «Усього» (R01G4) додається до рядка 5 декларації.
* Таблиця 2 — звільнені операції за кодом пільги; заповнюється при розрахунку з
  виданих ПН періоду (рядки зі ставкою «звільнено»), обсяги придбання (графи 6–9)
  вносяться вручну й зберігаються при перерахунку. «Усього» графи 5 (R02G5) —
  рядки 5 і 5.1 декларації.
* Таблиці 3 і 4 — показники у відсотках і відмітка «+».
"""
import re
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import float_compare, float_round

from .l10n_ua_vat_declaration_xml import _dec2, _int, escape

# Умовний код, якщо пільги немає в довіднику (Порядок, розд. V-1 п. 2).
UNKNOWN_BENEFIT_CODE = '99999999'
BENEFIT_CODE_RE = re.compile(r'(1406\d{4})|(9{8})')


def _r2(value):
    return float_round(value or 0.0, precision_digits=2)


class L10nUaVatDeclarationD4Table1(models.Model):
    _name = 'l10n_ua.vat.declaration.d4.t1.line'
    _description = 'Д4, таблиця 1: операції, що не є об\'єктом / за межами України'
    _order = 'operation_type, sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    operation_type = fields.Selection(
        [('non_object', 'Не є об\'єктом оподаткування'),
         ('abroad', 'Послуги за межами митної території (п. 186.2, 186.3)')],
        string='Частина таблиці', required=True, default='non_object')
    name = fields.Char(string='Назва операції', required=True, help='Графа 2')
    article = fields.Char(string='Пункт, стаття ПКУ', required=True,
                          help='Графа 3, наприклад «196.1.1» або «186.3»')
    amount = fields.Monetary(string='Обсяг постачання без ПДВ', currency_field='currency_id',
                             help='Графа 4')


class L10nUaVatDeclarationD4Table2(models.Model):
    _name = 'l10n_ua.vat.declaration.d4.t2.line'
    _description = 'Д4, таблиця 2: ПДВ, не сплачений у зв\'язку з пільгою'
    _order = 'sequence, benefit_code, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Найменування пільги', required=True,
                       help='Графа 2 — згідно з довідником пільг')
    benefit_code = fields.Char(
        string='Код пільги', required=True, default=UNKNOWN_BENEFIT_CODE,
        help='Графа 3: код з довідника пільг (14060000…) або умовний 99999999, '
             'якщо пільги немає в довіднику')
    supply_amount = fields.Monetary(
        string='Обсяг звільнених операцій', currency_field='currency_id',
        help='Графа 5: обсяг постачання, звільненого від оподаткування')
    purchase_20 = fields.Monetary(string='Придбання 20 %', currency_field='currency_id',
                                  help='Графа 6: придбане за ставкою 20 % і використане '
                                       'в пільгових операціях (без ПДВ)')
    purchase_7 = fields.Monetary(string='Придбання 7 %', currency_field='currency_id',
                                 help='Графа 7')
    purchase_0 = fields.Monetary(string='Придбання 0 % / звільнені',
                                 currency_field='currency_id', help='Графа 8')
    purchase_14 = fields.Monetary(string='Придбання 14 %', currency_field='currency_id',
                                  help='Графа 9')
    vat_unpaid = fields.Monetary(
        string='ПДВ, не сплачений', currency_field='currency_id',
        compute='_compute_vat_unpaid', store=True, readonly=False,
        help='Графа 4 = обсяг × 20 % − придбання 20 % × 20 % − придбання 7 % × 7 % − '
             'придбання 14 % × 14 %; від\'ємне значення не заповнюється')

    @api.depends('supply_amount', 'purchase_20', 'purchase_7', 'purchase_14')
    def _compute_vat_unpaid(self):
        # Формула Порядку, розд. V-1 п. 3 (у тексті — зображення, відновлено з
        # розшифровки позначень): ПДВ_несплач = V_пост × 20 % − V_прид20 × 20 % −
        # V_прид7 × 7 % − V_прид14 × 14 %. Придбання за 0 % / звільнені (графа 8) ПДВ
        # не містять і на суму не впливають. Від'ємний результат графа 4 не показує
        # (примітка ** до таблиці 2).
        for line in self:
            vat = _r2(line.supply_amount * 0.20 - line.purchase_20 * 0.20
                      - line.purchase_7 * 0.07 - line.purchase_14 * 0.14)
            line.vat_unpaid = max(vat, 0.0)


class L10nUaVatDeclarationD4(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    d4_t1_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d4.t1.line', 'declaration_id',
        string='Д4, таблиця 1', copy=False)
    d4_t2_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d4.t2.line', 'declaration_id',
        string='Д4, таблиця 2', copy=False)
    d4_t1_total = fields.Monetary(
        string='Д4, таблиця 1: усього', currency_field='currency_id',
        compute='_compute_d4_totals',
        help='Переноситься до рядка 5 декларації (разом з графою 5 таблиці 2)')
    d4_t2_total = fields.Monetary(
        string='Д4, таблиця 2: усього графа 5', currency_field='currency_id',
        compute='_compute_d4_totals', help='Переноситься до рядків 5 і 5.1 декларації')
    # Таблиця 3 — підприємства (організації) осіб з інвалідністю.
    d4_disabled_staff_pct = fields.Float(
        string='ЧПІ, %', digits=(5, 2),
        help='Відсоток осіб з інвалідністю (основне місце роботи) від середньооблікової '
             'чисельності штатних працівників за попередній період')
    d4_disabled_payroll_pct = fields.Float(
        string='ФОПІ, %', digits=(5, 2),
        help='Відсоток фонду оплати праці осіб з інвалідністю від загальних витрат на '
             'оплату праці за звітний період')
    d4_processing_cost_pct = fields.Float(
        string='БВТ, %', digits=(5, 2),
        help='Відсоток витрат з переробки сировини, комплектувальних, покупних '
             'товарів/послуг щодо ціни постачання виготовлених звільнених товарів/послуг')
    # Таблиця 4 — п. 68 підрозд. 10 розд. XX ПКУ.
    d4_own_production_pct = fields.Float(
        string='Питома вага доходу від власної продукції, %', digits=(5, 2),
        help='Частка доходу від реалізації продукції власного виробництва та продуктів її '
             'переробки в загальному доході за звітний період (має бути понад 90 %)')
    d4_capacity_mark = fields.Boolean(
        string='Виробничі потужності лише в населених пунктах за п. 68',
        help='Відмітка «+» у таблиці 4')

    @api.depends('d4_t1_line_ids.amount', 'd4_t2_line_ids.supply_amount')
    def _compute_d4_totals(self):
        for rec in self:
            rec.d4_t1_total = sum(rec.d4_t1_line_ids.mapped('amount'))
            rec.d4_t2_total = sum(rec.d4_t2_line_ids.mapped('supply_amount'))

    # ------------------------------------------------------------------ розрахунок

    def _calculate_from_registers(self):
        """Після базового розрахунку: таблиця 2 з реєстру й рядок 5 += таблиця 1.

        Базовий розрахунок заповнює рядки 5 і 5.1 звільненими обсягами виданих ПН;
        рядок 5 доповнюємо підсумком таблиці 1 Д4 (не об'єкт / за межами України),
        щоб «Розрахувати» не губило ручні рядки таблиці 1.
        """
        res = super()._calculate_from_registers()
        self._d4_fill_table2()
        extra = float_round(sum(self.d4_t1_line_ids.mapped('amount')), precision_digits=0)
        if extra:
            self.line_5_base = (self.line_5_base or 0.0) + extra
        return res

    @staticmethod
    def _d4_normalize_code(code):
        code = re.sub(r'\D', '', code or '')
        return code or UNKNOWN_BENEFIT_CODE

    def _d4_benefit_amounts(self):
        """Звільнені обсяги виданих ПН періоду за кодом пільги: {код: сума}.

        Основа — графа «Звільнено» реєстру (та сама, що й рядок 5.1), щоб підсумок
        таблиці 2 збігався з декларацією. Сума рядка реєстру розподіляється між
        кодами пільг пропорційно базі рядків ПН зі ставкою «звільнено»; рядок
        реєстру без ПН або без коду пільги — під умовним кодом 99999999.
        """
        self.ensure_one()
        amounts = defaultdict(float)
        lines = self.register_issued_id.line_ids.filtered(
            lambda l: l.doc_type != 'rk' and float_round(
                l.base_exempt or 0.0, precision_digits=2))
        for line in lines:
            exempt = line.tax_invoice_id.line_ids.filtered(lambda il: il.vat_rate == 'exempt')
            by_code = defaultdict(float)
            for inv_line in exempt:
                by_code[self._d4_normalize_code(inv_line.benefit_code)] += inv_line.base_amount
            base = sum(by_code.values())
            if not by_code or float_compare(base, 0.0, precision_digits=2) == 0:
                amounts[UNKNOWN_BENEFIT_CODE] += line.base_exempt
                continue
            left = line.base_exempt
            codes = sorted(by_code)
            for code in codes[:-1]:
                part = _r2(line.base_exempt * by_code[code] / base)
                amounts[code] += part
                left -= part
            amounts[codes[-1]] += _r2(left)
        return {code: _r2(amount) for code, amount in amounts.items()}

    def _d4_fill_table2(self):
        """Перезаповнити таблицю 2, зберігши ручні назви й обсяги придбання за кодом."""
        self.ensure_one()
        kept = {line.benefit_code: {
            'name': line.name, 'sequence': line.sequence,
            'purchase_20': line.purchase_20, 'purchase_7': line.purchase_7,
            'purchase_0': line.purchase_0, 'purchase_14': line.purchase_14,
        } for line in self.d4_t2_line_ids}
        amounts = self._d4_benefit_amounts()
        commands = [(5, 0, 0)]
        for code in sorted(amounts):
            vals = kept.get(code) or {
                'name': (_('Пільга, відсутня в довіднику пільг')
                         if code == UNKNOWN_BENEFIT_CODE
                         else _('Пільга за кодом %s', code)),
            }
            commands.append((0, 0, dict(vals, benefit_code=code,
                                        supply_amount=amounts[code])))
        self.write({'d4_t2_line_ids': commands})

    # ------------------------------------------------------------------ перевірки

    def _d4_table34_filled(self):
        return bool(self.d4_disabled_staff_pct or self.d4_disabled_payroll_pct
                    or self.d4_processing_cost_pct or self.d4_own_production_pct
                    or self.d4_capacity_mark)

    def _d4_needed(self):
        """Д4 обов'язковий при заповненому рядку 5 і для таблиць 3/4 (Порядок, розд. V п. 3)."""
        self.ensure_one()
        return bool(float_round(self.line_5_base or 0.0, precision_digits=0)
                    or self.d4_t1_line_ids or self.d4_t2_line_ids
                    or self._d4_table34_filled())

    def _vat_xml_problems(self):
        problems = super()._vat_xml_problems()
        if self._d4_needed():
            problems += self._d4_check()
        return problems

    def _d4_check(self):
        self.ensure_one()
        problems = []
        t1 = self.d4_t1_line_ids
        t2 = self.d4_t2_line_ids
        t1_total = float_round(sum(t1.mapped('amount')), precision_digits=0)
        t2_total = float_round(sum(t2.mapped('supply_amount')), precision_digits=0)
        if float_round(self.line_5_1_base or 0.0, precision_digits=0) and not t2:
            problems.append(_('Д4: таблицю 2 не заповнено — натисніть «Розрахувати»'))
        if t2_total != float_round(self.line_5_1_base or 0.0, precision_digits=0):
            problems.append(_('Д4: усього графи 5 таблиці 2 (%(t2).0f) не дорівнює рядку 5.1 '
                              '(%(r).0f)', t2=t2_total, r=self.line_5_1_base or 0.0))
        if t1_total + t2_total != float_round(self.line_5_base or 0.0, precision_digits=0):
            problems.append(_('Д4: таблиця 1 (%(t1).0f) + графа 5 таблиці 2 (%(t2).0f) не '
                              'дорівнює рядку 5 (%(r).0f) — натисніть «Розрахувати»',
                              t1=t1_total, t2=t2_total, r=self.line_5_base or 0.0))
        bad_codes = t2.filtered(lambda l: not BENEFIT_CODE_RE.fullmatch(l.benefit_code or ''))
        if bad_codes:
            problems.append(_('Д4: код пільги — 8 цифр «1406…» або умовний 99999999: %s')
                            % ', '.join(bad_codes.mapped(lambda l: l.benefit_code or '?')[:5]))
        if len(set(t2.mapped('benefit_code'))) != len(t2):
            problems.append(_('Д4: код пільги повторюється в таблиці 2'))
        if t2.filtered(lambda l: not (l.name or '').strip()) or \
                t1.filtered(lambda l: not (l.name or '').strip() or not (l.article or '').strip()):
            problems.append(_('Д4: назва операції / пільги і стаття ПКУ обов\'язкові'))
        if any(min(l.purchase_20, l.purchase_7, l.purchase_0, l.purchase_14) < 0 for l in t2):
            problems.append(_('Д4: обсяги придбання (графи 6–9) не можуть бути від\'ємними'))
        for value in (self.d4_disabled_staff_pct, self.d4_disabled_payroll_pct,
                      self.d4_processing_cost_pct, self.d4_own_production_pct):
            if not 0 <= (value or 0.0) <= 100:
                problems.append(_('Д4: відсотки таблиць 3 і 4 — від 0 до 100'))
                break
        return problems

    # ------------------------------------------------------------------ XML

    def _vat_attachments(self):
        res = super()._vat_attachments()
        if self._d4_needed():
            res.append(('d4', self._render_d4))
        return res

    def _render_d4(self, head):
        """Д4: таблиці 1–4 у порядку XSD J0299326 (стовпцями з ROWNUM)."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]

        def column(tag, rows, fmt):
            return ''.join(f'<{tag} ROWNUM="{n}">{fmt(row)}</{tag}>'
                           for n, row in enumerate(rows, 1))

        def money_column(tag, rows, field, only_positive=False):
            cells = []
            for n, row in enumerate(rows, 1):
                value = _r2(row[field])
                if value > 0 or (not only_positive and value):
                    cells.append(f'<{tag} ROWNUM="{n}">{_dec2(value)}</{tag}>')
            return ''.join(cells)

        t1_all = self.d4_t1_line_ids.sorted(lambda l: (l.sequence, l.id))
        for prefix, total_tag, op_type in (('T11', 'R011G4', 'non_object'),
                                           ('T12', 'R012G4', 'abroad')):
            rows = t1_all.filtered(lambda l, t=op_type: l.operation_type == t)
            if not rows:
                continue
            body += [
                column(f'{prefix}RXXXXG2S', rows, lambda r: escape(r.name or '')),
                column(f'{prefix}RXXXXG3S', rows, lambda r: escape(r.article or '')),
                column(f'{prefix}RXXXXG4', rows, lambda r: _dec2(r.amount)),
                f'<{total_tag}>{_dec2(sum(rows.mapped("amount")))}</{total_tag}>',
            ]
        if t1_all:
            body.append(f'<R01G4>{_int(sum(t1_all.mapped("amount")))}</R01G4>')

        t2 = self.d4_t2_line_ids.sorted(lambda l: (l.sequence, l.benefit_code, l.id))
        if t2:
            body += [
                column('T2RXXXXG2S', t2, lambda r: escape(r.name or '')),
                column('T2RXXXXG3', t2, lambda r: r.benefit_code),
                # Графа 4: від'ємне значення не заповнюється (примітка ** таблиці 2).
                money_column('T2RXXXXG4', t2, 'vat_unpaid', only_positive=True),
                column('T2RXXXXG5', t2, lambda r: _dec2(r.supply_amount)),
                money_column('T2RXXXXG6', t2, 'purchase_20'),
                money_column('T2RXXXXG7', t2, 'purchase_7'),
                money_column('T2RXXXXG8', t2, 'purchase_0'),
                money_column('T2RXXXXG9', t2, 'purchase_14'),
            ]
            for col, field in (('4', 'vat_unpaid'), ('5', 'supply_amount'),
                               ('6', 'purchase_20'), ('7', 'purchase_7'),
                               ('8', 'purchase_0'), ('9', 'purchase_14')):
                total = sum(t2.mapped(field))
                if col == '5' or float_round(total, precision_digits=0):
                    body.append(f'<R02G{col}>{_int(total)}</R02G{col}>')

        # Таблиці 3 і 4: у XSD тип DGdecimal0 — відсотки лише цілими (округлення
        # за арифметичними правилами), хоча форма для таблиці 4 просить два знаки.
        for tag, value in (('R04G2', self.d4_disabled_staff_pct),
                           ('R05G2', self.d4_disabled_payroll_pct),
                           ('R06G2', self.d4_processing_cost_pct),
                           ('R07G2', self.d4_own_production_pct)):
            if float_round(value or 0.0, precision_digits=0):
                body.append(f'<{tag}>{_int(value)}</{tag}>')
        if self.d4_capacity_mark:
            body.append('<R08G2>1</R08G2>')
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d4'), self._render_head(head), ''.join(body))
