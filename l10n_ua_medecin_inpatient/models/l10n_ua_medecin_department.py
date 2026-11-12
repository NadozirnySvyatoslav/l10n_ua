from datetime import datetime, time, timedelta

from odoo import api, fields, models


MOVEMENT_KEYS = (
    'count_start', 'admitted', 'transferred_in', 'transferred_out',
    'discharged', 'died', 'count_end', 'bed_days',
)


class L10nUaMedecinDepartment(models.Model):
    """Відділення стаціонару з ліжковим фондом.

    Рух хворих (ф. 007/о) і показники використання ліжкового фонду
    рахуються методом `_get_bed_movement` за перебуваннями пацієнтів у
    відділенні (епізод + переведення між відділеннями).
    """
    _name = 'l10n_ua.medecin.department'
    _description = 'Відділення стаціонару'
    _order = 'sequence, name'

    name = fields.Char(string='Назва', required=True)
    code = fields.Char(string='Код')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Заклад', required=True, index=True,
        default=lambda self: self.env.company)
    specialty_id = fields.Many2one(
        'l10n_ua.medecin.specialty', string='Профіль', ondelete='restrict')
    head_id = fields.Many2one(
        'hr.employee', string='Завідувач', ondelete='set null',
        domain="[('company_id', 'in', (company_id, False))]")
    note = fields.Text(string='Примітки')

    bed_ids = fields.One2many(
        'l10n_ua.medecin.bed', 'department_id', string='Ліжка')
    bed_count = fields.Integer(
        string='Ліжковий фонд', compute='_compute_bed_fund',
        help='Кількість ліжок, розгорнутих на сьогодні.')
    bed_occupied_count = fields.Integer(
        string='Пацієнтів у відділенні', compute='_compute_bed_fund',
        help='Кількість пацієнтів у стані «Госпіталізовано» в цьому відділенні.')
    bed_free_count = fields.Integer(
        string='Вільних ліжок', compute='_compute_bed_fund',
        help='Ліжковий фонд мінус пацієнти у відділенні (не менше нуля).')

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Код відділення має бути унікальним у межах закладу.',
    )

    @api.depends('bed_ids.active', 'bed_ids.date_open', 'bed_ids.date_close')
    def _compute_bed_fund(self):
        today = fields.Date.context_today(self)
        groups = self.env['l10n_ua.medecin.admission']._read_group(
            [('department_id', 'in', self.ids), ('state', '=', 'admitted')],
            ['department_id'], ['__count'])
        patients = {dept.id: count for dept, count in groups}
        for dept in self:
            dept.bed_count = len(dept.bed_ids.filtered(lambda b: b._is_deployed_on(today)))
            dept.bed_occupied_count = patients.get(dept.id, 0)
            dept.bed_free_count = max(dept.bed_count - dept.bed_occupied_count, 0)

    def action_view_beds(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'l10n_ua.medecin.bed',
            'view_mode': 'list,form',
            'domain': [('department_id', '=', self.id)],
            'context': {'default_department_id': self.id},
        }

    # === Рух хворих і ліжковий фонд ===

    def _get_bed_movement(self, date_from, date_to):
        """Рух хворих і ліжко-дні по відділеннях `self` за [date_from, date_to].

        Дати — календарні дні в часовому поясі закладу. Перебування пацієнта
        у відділенні — відрізок від поступлення (госпіталізації чи переведення
        у відділення) до вибуття (виписки, смерті чи переведення в інше
        відділення); подія належить дню, на який припадає її місцева дата.

        * count_start — пацієнтів на початок date_from (поступили раніше, ще
          не вибули на початок дня);
        * count_end — пацієнтів на кінець date_to (поступили не пізніше
          date_to і не вибули до кінця дня), рахується незалежно від подій;
        * admitted / transferred_in / transferred_out / discharged / died —
          події за період; виписані — усі живі вибулі (додому, в інший
          заклад, самовільно), померлі окремо;
        * bed_days — ліжко-дні: кількість північ, що пацієнт провів у
          відділенні в межах періоду, плюс 1 за перебування, що почалося і
          закінчилося в один день (узгоджено з admission.bed_days);
        * bed_count — ліжковий фонд на date_to; avg_beds — середнє число
          розгорнутих ліжок за період (ліжко-дні фонду / днів у періоді).

        Баланс: count_end = count_start + admitted + transferred_in
        − discharged − died − transferred_out.
        """
        result = {dept.id: dict.fromkeys(MOVEMENT_KEYS, 0) for dept in self}
        if not self:
            return result
        period_days = (date_to - date_from).days + 1
        for dept in self:
            res = result[dept.id]
            beds = dept.bed_ids
            res['bed_count'] = len(beds.filtered(lambda b: b._is_deployed_on(date_to)))
            res['avg_beds'] = sum(
                b._deployed_days(date_from, date_to) for b in beds) / period_days

        # Відбір з запасом у добу на часові пояси; точний відбір — за місцевими датами.
        dt_from = datetime.combine(date_from - timedelta(days=1), time.min)
        dt_to = datetime.combine(date_to + timedelta(days=2), time.min)
        admissions = self.env['l10n_ua.medecin.admission'].search([
            ('company_id', 'in', self.company_id.ids),
            ('state', 'in', ('admitted', 'discharged')),
            ('date_admission', '<', dt_to),
            '|', ('state', '=', 'admitted'), ('date_discharge', '>=', dt_from),
        ])
        for adm in admissions:
            segments = adm._get_department_stays()
            for dept, start, end, kind_in, kind_out in segments:
                res = result.get(dept.id)
                if res is None:
                    continue
                d_start = adm._local_date(start)
                d_end = adm._local_date(end) if end else None
                # Початок / кінець періоду (незалежний підрахунок для балансу).
                if d_start < date_from and (d_end is None or d_end >= date_from):
                    res['count_start'] += 1
                if d_start <= date_to and (d_end is None or d_end > date_to):
                    res['count_end'] += 1
                if date_from <= d_start <= date_to:
                    res[kind_in] += 1
                if d_end is not None and date_from <= d_end <= date_to:
                    res[kind_out] += 1
                # Ліжко-дні: північ D→D+1 рахується, якщо d_start ≤ D < d_end.
                last = date_to if d_end is None else min(date_to, d_end - timedelta(days=1))
                first = max(date_from, d_start)
                res['bed_days'] += max((last - first).days + 1, 0)
            # Поступив і вибув того ж дня — 1 ліжко-день відділенню вибуття.
            if adm.state == 'discharged' and segments:
                d_in = adm._local_date(adm.date_admission)
                d_out = adm._local_date(adm.date_discharge)
                dept = segments[-1][0]
                if d_in == d_out and date_from <= d_out <= date_to and dept.id in result:
                    result[dept.id]['bed_days'] += 1
        return result
