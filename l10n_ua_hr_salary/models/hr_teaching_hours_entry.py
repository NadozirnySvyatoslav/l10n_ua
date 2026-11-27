"""Погодинна оплата за проведення навчальних занять (#417).

Педагог, викладач чи запрошений лектор отримує за години навчальних занять
понад оклад (або без окладу) погодинну оплату: години × ставка. З 01.01.2027
ставка — відсоток базової величини за ставками погодинної оплати ПКМУ № 1078
(пп. 4 п. 2), округлений до гривні: до 0,5 відкидається, від 0,5 — угору
(примітка 1). Академікам і членам-кореспондентам ставка вища на 25 %
(примітка 3); підвищену ставку округлюємо так само. Ставки включають оплату
за дні відпустки (примітка 4), тож відпускні з цих годин окремо не рахуються.

До 01.01.2027 діють ставки додатка 5 до ПКМУ № 1298: їх у даних немає, тому
для такого періоду ставку вносять вручну.

Години за місяць розрахунку стають нарахуванням «Погодинна оплата за
навчальні заняття» (TEACH_HOURLY), незалежно від форми оплати основної роботи.
Відпускні в ставку вже входять, тож TEACH_HOURLY не потрапляє в середню для
відпусток (l10n_ua_vacation_included, рішення Р1 у #417), але входить у
середньомісячний за 2 місяці (вихідна допомога); ПДФО, ВЗ, ЄСВ і база
лікарняних — як для зарплати.

Записи за місяць проведеного (done) листка закриті: їх не можна ні додати, ні
змінити, ні видалити, поки листок не повернуто в чернетку, інакше години
мовчки розійшлися б із виплаченим.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

ACADEMICIAN_RAISE = 1.25


class HrTeachingHoursEntry(models.Model):
    _name = 'hr.teaching.hours.entry'
    _description = 'Години навчальних занять (погодинна оплата)'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Заняття', required=True,
        help='Дисципліна, група, вид занять.')
    employee_id = fields.Many2one(
        'hr.employee', string='Працівник', required=True, index=True)
    date = fields.Date(
        string='Дата', required=True, index=True, default=fields.Date.context_today,
        help='Дата занять. Визначає місяць нарахування і ставку на цю дату.')
    hours = fields.Float(string='Години', required=True, default=0.0)
    pay_scheme_line_id = fields.Many2one(
        'hr.pay.scheme.line', string='Ставка за схемою',
        domain=[('kind', '=', 'hourly')],
        help='Контингент і науковий ступінь / вчене звання за ставками погодинної '
             'оплати ПКМУ № 1078 (з 01.01.2027). Порожньо — ставка вручну.')
    academician = fields.Boolean(
        string='Академік / член-кореспондент',
        help='Ставка підвищується на 25 % (примітка 3 до ставок ПКМУ № 1078).')
    hourly_rate = fields.Monetary(
        string='Ставка за годину', compute='_compute_hourly_rate', store=True,
        readonly=False, currency_field='currency_id',
        help='За схемою — базова величина на дату × відсоток, до гривні. Без '
             'схеми (зокрема до 2027 року, ставки додатка 5 до ПКМУ № 1298) — '
             'вводиться вручну.')
    amount = fields.Monetary(
        string='Сума', compute='_compute_amount', store=True,
        currency_field='currency_id')
    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    _hours_positive = models.Constraint(
        'CHECK(hours >= 0)', 'Кількість годин не може бути відʼємною.')
    _rate_positive = models.Constraint(
        'CHECK(hourly_rate >= 0)', 'Ставка не може бути відʼємною.')

    @api.model
    def _scheme_rate(self, line, on_date, academician=False):
        """Ставка за годину за схемою на дату, або 0, якщо базової величини немає."""
        value = self.env['hr.pay.base.value']._value_on(on_date)
        if not (line and value):
            return 0.0
        rate = line._amount_from(value)
        if academician:
            rate = float_round(rate * ACADEMICIAN_RAISE, precision_digits=0,
                               rounding_method='HALF-UP')
        return rate

    @api.depends('pay_scheme_line_id', 'date', 'academician')
    def _compute_hourly_rate(self):
        for entry in self:
            if entry.pay_scheme_line_id:
                entry.hourly_rate = self._scheme_rate(
                    entry.pay_scheme_line_id, entry.date, entry.academician)

    @api.depends('hours', 'hourly_rate')
    def _compute_amount(self):
        for entry in self:
            entry.amount = float_round(entry.hours * entry.hourly_rate, precision_digits=2)

    @api.constrains('pay_scheme_line_id', 'date')
    def _check_scheme_date(self):
        for entry in self:
            line = entry.pay_scheme_line_id
            if not line:
                continue
            line._check_applies_on(entry.date, what=_('Заняття %s', entry.name))
            if not self.env['hr.pay.base.value']._value_on(entry.date):
                raise ValidationError(_(
                    'На %s немає базової величини: внесіть її в «Базові величини».',
                    entry.date))

    # ------------------------------------------------------------------
    # Закритий місяць: записи в періоді проведеного листка (К9 #417)
    # ------------------------------------------------------------------
    def _check_payslip_not_done(self):
        """Відмова, якщо дата запису — у періоді проведеного листка працівника.

        Листок шукаємо з sudo лише для перевірки, чи він є: табельник, який
        вносить години, може не мати права читати листки.
        """
        Payslip = self.env['hr.payslip'].sudo()
        for entry in self:
            slip = Payslip.search([
                ('employee_id', '=', entry.employee_id.id),
                ('company_id', '=', entry.company_id.id),
                ('state', '=', 'done'),
                ('date_from', '<=', entry.date),
                ('date_to', '>=', entry.date),
            ], limit=1)
            if slip:
                raise UserError(_(
                    'Години %(emp)s за %(date)s уже в проведеному листку '
                    '«%(slip)s». Спершу скасуйте листок (поверніть у чернетку), '
                    'потім змініть години.',
                    emp=entry.employee_id.name, date=entry.date,
                    slip=slip.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        entries = super().create(vals_list)
        entries._check_payslip_not_done()
        return entries

    def write(self, vals):
        self._check_payslip_not_done()
        res = super().write(vals)
        if {'date', 'employee_id', 'company_id'} & set(vals):
            self._check_payslip_not_done()
        return res

    def unlink(self):
        self._check_payslip_not_done()
        return super().unlink()
