import base64
import csv
import io
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.tools.sql import column_exists


def _company_signatory(env, field_name):
    """Підписант із картки компанії, стійкий до оновлення бази.

    Поля-підписанти на res_company і поля звітів, що беруть їх за
    замовчуванням, з'явилися одним релізом. Під час оновлення Odoo ініціалізує
    нову колонку звіту раніше, ніж додає колонку на res_company, а
    `_init_column` обчислює default навіть для порожньої таблиці — читання
    поля компанії падає з UndefinedColumn і валить оновлення бази цілком.
    Поки колонки немає, підписант лишається порожнім: користувач обере його
    у формі.
    """
    if not column_exists(env.cr, 'res_company', field_name):
        return False
    return env.company[field_name]


def _was_employed_on(employee, as_of):
    """Return True if employee (active or archived) was employed on as_of date.

    Employment is detected per-version: at least one contract version has a
    start date <= as_of AND either no end date or an end date >= as_of.
    This handles rehires correctly — e.g. a fixed-term version that ended
    in 2023 followed by an open-ended version starting in 2024 keeps the
    employee 'employed' in 2025 via the second version, even though the
    first version's end date is earlier than as_of.

    The day of departure is included on purpose (end >= as_of): the last
    working day still counts as employed. This snapshot semantics differs
    from headcount reports that use strict > to count active days only.

    Falls back to employee-level hire_date / departure_date when no contract
    version carries dates. Reading uses active_test=False so archived
    employees' versions stay visible.
    """
    if not as_of:
        return True

    # Contract dates live on hr.version behind hr.group_hr_manager, while the
    # reports built on this helper are open to HR officers (see
    # ir.model.access.csv). Read the dates as superuser: the caller already
    # selected the employees under its own access rights, and only the dates
    # behind the employed/not-employed decision are read here.
    employee = employee.sudo().with_context(active_test=False)

    def has(rec, name):
        return name in rec._fields

    has_any_version_date = False
    for v in employee.version_ids:
        starts = [v.contract_date_start]
        if has(v, 'date_start'):
            starts.append(v.date_start)
        if has(v, 'date_version'):
            starts.append(v.date_version)
        ends = [v.contract_date_end]
        if has(v, 'date_end'):
            ends.append(v.date_end)

        version_starts = [d for d in starts if d]
        version_ends = [d for d in ends if d]
        if version_starts or version_ends:
            has_any_version_date = True
        if not any(s <= as_of for s in version_starts):
            continue
        if not version_ends or max(version_ends) >= as_of:
            return True

    if has_any_version_date:
        return False

    if not employee.hire_date or employee.hire_date > as_of:
        return False

    departure = employee.departure_date if has(employee, 'departure_date') else False
    return not departure or departure >= as_of


def _employment_event_dates(employee, event):
    """Return dated hires or departures from contract-version history."""
    employee = employee.sudo().with_context(active_test=False)
    version_field = (
        'contract_date_start' if event == 'hire' else 'contract_date_end')
    dates = [getattr(version, version_field, False)
             for version in employee.version_ids]
    dates = [value for value in dates if value]
    if dates:
        return dates
    fallback = 'hire_date' if event == 'hire' else 'departure_date'
    value = getattr(employee, fallback, False)
    return [value] if value else []

class HrEmployeeListReport(models.Model):
    """Employee List Report (Список працівників).

    Snapshot of active employees as of a specific date. Saved and
    reusable; can be regenerated and printed to PDF.
    """
    _name = 'hr.employee.list.report'
    _description = 'Employee List Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Список працівників станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = 'Список працівників'

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.with_context(active_test=False).employee_ids)

    def _domain_employees(self):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
        ]

    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(
                active_test=False).search(rec._domain_employees())
            as_of = rec.date
            # Keep only employees (active or archived) employed on the date.
            employees = candidates.filtered(
                lambda e: _was_employed_on(e, as_of))

            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_list'
        ).report_action(self)


class HrEmployeeMilitaryReport(models.Model):
    """Military Personnel Report (Військовозобов'язані)."""
    _name = 'hr.employee.military.report'
    _description = 'Military Personnel Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    reserved_count = fields.Integer(
        string='Reserved',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()
    # Підписанти Списків за п. 40 Порядку № 1487: щороку до 25 січня (станом
    # на 1 січня) Списки підписують керівник і особа, відповідальна за ведення
    # військового обліку, після чого їх реєструє служба діловодства.
    director_id = fields.Many2one(
        'hr.employee', string='Керівник',
        default=lambda self: _company_signatory(self.env, 'director_id'),
    )
    military_officer_id = fields.Many2one(
        'hr.employee', string='Відповідальний за військовий облік',
        default=lambda self: _company_signatory(self.env, 'military_officer_id'),
    )
    registration_ref = fields.Char(
        string='Реєстраційний номер',
        help='Номер, під яким Списки зареєстровано у службі діловодства '
             '(п. 40 Порядку № 1487).')

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Військовозобов'язані станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = "Військовозобов'язані"

    def _get_form5_groups(self):
        """Розкласти працівників по чотирьох групах Списків (п. 36 № 1487).

        Повертає список кортежів (код, назва, працівники) у порядку груп
        бланка; порожні групи не пропускаються — у формі має бути видно всі
        чотири, навіть якщо в якійсь із них нікого немає.

        Усередині групи спершу йдуть особи з мобілізаційними розпорядженнями,
        у послідовності зростання номерів команд, далі — решта за абеткою.
        """
        self.ensure_one()
        employees = self.with_context(active_test=False).employee_ids
        labels = dict(
            self.env['hr.employee']._fields['military_list_group'].selection)

        def sort_key(employee):
            team = (employee.military_mob_team or '').strip()
            # Команди сортуються як числа, коли це числа: '10' має йти після
            # '9', а не між '1' і '2'.
            return (
                0 if team else 1,
                (0, int(team)) if team.isdigit() else (1, team.lower()),
                (employee.name or '').lower(),
            )

        groups = []
        for code in ('officers', 'soldiers', 'women', 'conscripts'):
            members = employees.filtered(
                lambda e: e.military_list_group == code)
            groups.append((code, labels.get(code, code),
                           members.sorted(key=sort_key)))
        return groups

    @api.depends('employee_ids', 'employee_ids.military_reservation')
    def _compute_employee_count(self):
        for rec in self:
            employees = rec.with_context(active_test=False).employee_ids
            rec.employee_count = len(employees)
            rec.reserved_count = len(employees.filtered('military_reservation'))


    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(active_test=False).search([
                ('company_id', '=', rec.company_id.id),
                ('military_register_category', 'in',
                    ['conscript', 'liable', 'reservist']),
            ])
            as_of = rec.date
            employees = candidates.filtered(
                lambda e: rec._is_listed_on(e, as_of))
            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def _is_listed_on(self, employee, as_of):
        """Whether an employee belongs in Form 5 on the report date.

        Paragraph 44 keeps an excluded person in the Lists only until the end
        of the exclusion year.  Without this guard an active employee marked
        as excluded by age remained in every later annual List because the
        employment-period check continued to return true.
        """
        self.ensure_one()
        excluded_on = employee.military_exclusion_date
        if excluded_on and as_of and excluded_on <= as_of:
            return excluded_on.year == as_of.year
        return _was_employed_on(employee, as_of)

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_military'
        ).report_action(self)

    def action_print_form5(self):
        """Друк Списків за офіційним бланком (додаток 5 до Порядку № 1487)."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_military_form5'
        ).report_action(self)

    # --- Експорт списку персонального військового обліку для ТЦК (#156) ---
    export_data = fields.Binary(string='Export File', readonly=True, copy=False)
    export_filename = fields.Char(string='Export File Name', readonly=True, copy=False)

    def action_export_csv(self):
        """Вивантажити Списки у CSV — граф у графу з бланком додатка 5.

        Використовується для звіряння облікових даних з ТЦК та СП (п. 34
        Порядку № 1487): колонки повторюють 18 граф форми в редакції ПКМУ
        № 916 від 30.07.2025, тож рядки можна зіставляти напряму.
        Файл — windows-1251 (для держсистем / Excel UA).
        """
        self.ensure_one()
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';')
        writer.writerow([
            '№', 'Категорія військового обліку', 'Військове звання',
            'Прізвище, власне ім\'я та по батькові', 'Дата народження',
            'Реєстраційний номер запису в ЄДР', 'РНОКПП', 'ВОС',
            'Реквізити військово-облікового документа',
            'Реквізити паспорта', 'Адреса місця проживання', 'ТЦК та СП',
            'Відстрочка', 'Спеціальний облік', 'Військова служба',
            'Мобілізаційне розпорядження', 'Посада, акт про призначення',
            'Реквізити повідомлення'])
        row_number = 0
        for _code, group_label, employees in self._get_form5_groups():
            if not employees:
                continue
            writer.writerow([group_label])
            for emp in employees:
                row_number += 1
                writer.writerow([
                    row_number,
                    dict(emp._fields['military_register_category'].selection).get(
                        emp.military_register_category, ''),
                    emp.military_rank_id.name or '',
                    emp.name or '',
                    emp.birthday.strftime('%d.%m.%Y') if emp.birthday else '',
                    emp.military_vin_code or '',
                    emp.rnokpp or '',
                    emp.military_specialty or '',
                    emp._military_document_label(),
                    emp._military_passport_label(),
                    emp._military_address_label(),
                    emp.military_tcc_id.name or '',
                    emp._military_deferment_label(),
                    emp._military_special_register_label(),
                    emp._military_service_label(),
                    emp._military_mob_order_label(),
                    emp._military_position_label(),
                    emp._military_notice_label(),
                ])
        content = buf.getvalue().encode('cp1251', 'replace')
        self.export_data = base64.b64encode(content)
        self.export_filename = 'vijskovyj_oblik_%s.csv' % (
            self.date.strftime('%Y_%m_%d') if self.date else 'list')
        return True


class HrMilitaryNotification(models.Model):
    """Повідомлення до ТЦК та СП про зміни у військовозобов'язаних (#156).

    Аудит-журнал повідомлень про прийняття / звільнення / зміну облікових
    даних (Постанова КМУ № 1487). На підтвердженні знімає snapshot ключових
    реквізитів і формує CSV-файл повідомлення для подання.
    """
    _name = 'hr.military.notification'
    _description = 'Military Notification to TCC'
    _inherit = ['mail.thread']
    _order = 'event_date desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False)
    notification_type = fields.Selection([
        ('hire', 'Прийняття на роботу'),
        ('dismissal', 'Звільнення'),
        ('data_change', 'Зміна облікових даних'),
    ], string='Type', required=True, default='hire', tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True)
    event_date = fields.Date(
        string='Event Date', required=True,
        default=fields.Date.context_today, tracking=True)
    military_tcc_id = fields.Many2one(
        'hr.military.tcc', related='employee_id.military_tcc_id',
        string='TCC', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ], string='Status', default='draft', tracking=True)
    submitted_date = fields.Date(string='Submitted On', readonly=True)
    deadline_date = fields.Date(
        string='Подати до', compute='_compute_deadline_date', store=True,
        help='Строк подання за п. 34 Порядку № 1487: сім днів з дня видання '
             'наказу про прийняття на роботу (навчання) чи звільнення; для '
             'змін облікових даних — до 5 числа наступного місяця.')
    is_overdue = fields.Boolean(
        string='Прострочено', compute='_compute_is_overdue', store=True,
        help='Повідомлення не подане, а строк уже минув.')

    @api.depends('notification_type', 'event_date')
    def _compute_deadline_date(self):
        for rec in self:
            if not rec.event_date:
                rec.deadline_date = False
            elif rec.notification_type == 'data_change':
                # «Щомісяця до 5 числа» — тобто до 5-го числа місяця,
                # наступного за місяцем, у якому зміну внесено.
                first_next_month = (rec.event_date.replace(day=1)
                                    + relativedelta(months=1))
                rec.deadline_date = first_next_month.replace(day=5)
            else:
                rec.deadline_date = rec.event_date + timedelta(days=7)

    @api.depends('deadline_date', 'state')
    def _compute_is_overdue(self):
        today = date.today()
        for rec in self:
            rec.is_overdue = bool(
                rec.state == 'draft'
                and rec.deadline_date
                and rec.deadline_date < today
            )

    @api.model
    def _cron_check_notification_deadlines(self):
        """Щоденний cron: підняти прапорець на прострочених повідомленнях.

        Обчислюване поле залежить від дат, а не від плину часу, тож саме воно
        на зміну календаря не перерахується — cron переписує його напряму й
        нагадує у чатері про кожне протерміноване повідомлення.
        """
        today = date.today()
        overdue = self.search([
            ('state', '=', 'draft'),
            ('deadline_date', '!=', False),
            ('deadline_date', '<', today),
            ('is_overdue', '=', False),
        ])
        if not overdue:
            return
        overdue.write({'is_overdue': True})
        for rec in overdue:
            rec.message_post(body=_(
                'Повідомлення до ТЦК та СП щодо %(employee)s не подане: строк '
                'сплив %(deadline)s (п. 34 Порядку № 1487).',
                employee=rec.employee_id.name,
                deadline=rec.deadline_date.strftime('%d.%m.%Y'),
            ))
    # Snapshot реквізитів на момент подання (аудит).
    snapshot_rnokpp = fields.Char(string='RNOKPP (snapshot)', readonly=True)
    snapshot_data = fields.Text(string='Data (snapshot)', readonly=True)
    export_data = fields.Binary(string='Notification File', readonly=True, copy=False)
    export_filename = fields.Char(readonly=True, copy=False)
    notes = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.military.notification') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            emp = rec.employee_id
            rec.snapshot_rnokpp = emp.rnokpp or ''
            rec.snapshot_data = (
                '%s; %s; ВОС %s; ТЦК %s; док. %s' % (
                    emp.name or '',
                    emp.birthday.strftime('%d.%m.%Y') if emp.birthday else '',
                    emp.military_specialty or '',
                    emp.military_tcc_id.name or '',
                    emp.military_document_number or ''))
            rec._build_export()
            rec.write({
                'state': 'submitted',
                'submitted_date': fields.Date.context_today(rec),
            })
        return True

    def _build_export(self):
        self.ensure_one()
        emp = self.employee_id
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';')
        type_label = dict(self._fields['notification_type'].selection).get(
            self.notification_type, '')
        writer.writerow(['Тип повідомлення', 'РНОКПП', 'ПІБ',
                         'Дата народження', 'ВОС', 'ТЦК та СП',
                         'Військовий документ', 'Дата події'])
        writer.writerow([
            type_label, emp.rnokpp or '', emp.name or '',
            emp.birthday.strftime('%d.%m.%Y') if emp.birthday else '',
            emp.military_specialty or '', emp.military_tcc_id.name or '',
            emp.military_document_number or '',
            self.event_date.strftime('%d.%m.%Y') if self.event_date else '',
        ])
        content = buf.getvalue().encode('cp1251', 'replace')
        self.export_data = base64.b64encode(content)
        self.export_filename = 'tcc_notification_%s.csv' % (self.name or '').replace(
            '/', '_')


class HrEmployeeMilitaryOperationalReport(models.Model):
    """Відомість оперативного військового обліку — журнал змін за період (ПКМУ № 1487).

    Tracks military-related events during a date range: hires, dismissals,
    register_category changes, reservation changes. Source data comes from
    mail.message tracking values on hr.employee (military_* fields are tracked
    automatically by Odoo's mail.thread when @tracking is set on the model).
    """
    _name = 'hr.employee.military.operational.report'
    _description = 'Військовий облік: відомість оперативного обліку'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date_from = fields.Date(
        string='Період з',
        required=True,
        default=lambda self: date.today().replace(day=1),
        tracking=True,
    )
    date_to = fields.Date(
        string='Період до',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    line_ids = fields.One2many(
        'hr.employee.military.operational.report.line',
        'report_id',
        string='Записи журналу',
    )
    line_count = fields.Integer(
        compute='_compute_line_count', store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.name = (
                    f"Оперативний облік {rec.date_from.strftime('%d.%m.%Y')} – "
                    f"{rec.date_to.strftime('%d.%m.%Y')}"
                )
            else:
                rec.name = "Оперативний військовий облік"

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_generate(self):
        """Build journal from hr.order events + employee tracking changes."""
        self.ensure_one()
        self.line_ids.unlink()
        lines = []
        Order = self.env.get('hr.order')

        # 1) Hires + dismissals from hr.order (if l10n_ua_hr_documents installed)
        if Order is not None:
            orders = Order.search([
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('order_type', 'in', ['hiring', 'dismissal']),
                ('company_id', '=', self.company_id.id),
                ('state', '!=', 'cancelled'),
            ])
            for order in orders:
                if not order.employee_id or order.employee_id.military_register_category == 'not_applicable':
                    continue
                event = 'Прийом на роботу' if order.order_type == 'hiring' else 'Звільнення'
                lines.append((0, 0, {
                    'date': order.date,
                    'employee_id': order.employee_id.id,
                    'event_type': order.order_type,
                    'description': f'{event} (наказ № {order.name})',
                }))

        # 2) Tracked field changes from mail.message
        domain = [
            ('model', '=', 'hr.employee'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        messages = self.env['mail.message'].search(domain)
        tracked_fields = (
            'military_register_category', 'military_fitness',
            'military_reservation', 'military_reservation_until',
            'military_medical_category',
        )
        for msg in messages:
            for tracking in msg.tracking_value_ids:
                if tracking.field_id.name not in tracked_fields:
                    continue
                employee = self.env['hr.employee'].browse(msg.res_id)
                if not employee.exists() or employee.company_id != self.company_id:
                    continue
                lines.append((0, 0, {
                    'date': msg.date.date(),
                    'employee_id': employee.id,
                    'event_type': 'change',
                    'description': (
                        f'{tracking.field_id.field_description}: '
                        f'{tracking.old_value_char or tracking.old_value_text or "—"} → '
                        f'{tracking.new_value_char or tracking.new_value_text or "—"}'
                    ),
                }))

        self.write({
            'line_ids': lines,
            'state': 'generated',
        })
        return True

    def action_draft(self):
        self.line_ids.unlink()
        self.write({'state': 'draft'})

    # --- Відомість оперативного обліку (додаток 12 до Порядку № 1487) ------
    # Журнал змін вище — робочий інструмент кадровика. Сама ж відомість, яка
    # за п. 33 зберігається разом зі Списками, — це зведення чисельностей за
    # тими самими групами, що й Списки. Обидва подання будуються з одних даних.
    director_id = fields.Many2one(
        'hr.employee', string='Керівник',
        default=lambda self: _company_signatory(self.env, 'director_id'),
    )
    military_officer_id = fields.Many2one(
        'hr.employee', string='Відповідальний за військовий облік',
        default=lambda self: _company_signatory(self.env, 'military_officer_id'),
    )

    def _get_operational_rows(self):
        """Порахувати рядки відомості оперативного обліку.

        Колонки — за бланком додатка 12: усього, мають мобілізаційні
        розпорядження, заброньовані, не заброньовані й без розпоряджень,
        прийнято та звільнено з 1 січня. Останні дві рахуються від початку
        року до кінця періоду відомості, а не за сам період: бланк вимагає
        накопичувальний підсумок з 1 січня.
        """
        self.ensure_one()
        # hire_date / departure_date живуть на hr.version за групою
        # hr.group_hr_user, а відомість відкрита і кадровому офіцеру без неї —
        # тому читаємо від суперюзера, як і `_was_employed_on` вище. Назовні
        # виходять лише знеособлені підсумки.
        employees = self.env['hr.employee'].sudo().with_context(
            active_test=False).search([
                ('company_id', '=', self.company_id.id),
                ('military_register_category', 'in',
                 ['conscript', 'liable', 'reservist']),
            ])
        year_start = date(self.date_to.year, 1, 1) if self.date_to else None

        def counts(records):
            # Totals in Appendix 12 are a snapshot as of date_to.  Historical
            # records remain available solely for the cumulative hired and
            # dismissed columns; otherwise archived or already excluded staff
            # inflated the current headcount forever.
            current = records.filtered(
                lambda e: _was_employed_on(e, self.date_to)
                and not (e.military_exclusion_date
                         and e.military_exclusion_date <= self.date_to))
            with_mob = current.filtered('military_mob_order_number')
            reserved = current.filtered(
                lambda e: e.military_reservation
                and not e.military_reservation_expired)
            hired = dismissed = 0
            if year_start:
                hired = len(records.filtered(
                    lambda e: any(
                        year_start <= value <= self.date_to
                        for value in _employment_event_dates(e, 'hire'))))
                dismissed = len(records.filtered(
                    lambda e: any(
                        year_start <= value <= self.date_to
                        for value in _employment_event_dates(e, 'dismissal'))))
            return {
                'total': len(current),
                'with_mob': len(with_mob),
                'reserved': len(reserved),
                'free': len(current - with_mob - reserved),
                'hired': hired,
                'dismissed': dismissed,
            }

        by_group = {
            code: employees.filtered(lambda e: e.military_list_group == code)
            for code in ('officers', 'soldiers', 'women', 'conscripts')
        }
        liable = by_group['officers'] + by_group['soldiers'] + by_group['women']
        rows = [
            {'number': '1', 'label': 'Військовозобов\'язані (у тому числі '
                                     'резервісти), із них:', **counts(liable)},
            {'number': '1.1', 'label': 'Військовозобов\'язані офіцерського '
                                       'складу (у тому числі резервісти)',
             **counts(by_group['officers'])},
            {'number': '1.2', 'label': 'Військовозобов\'язані рядового, '
                                       'сержантського та старшинського складу '
                                       '(у тому числі резервісти)',
             **counts(by_group['soldiers'])},
            {'number': '1.3', 'label': 'Військовозобов\'язані-жінки '
                                       '(у тому числі резервісти)',
             **counts(by_group['women'])},
            {'number': '2', 'label': 'Призовники',
             **counts(by_group['conscripts'])},
        ]
        return rows

    def action_print(self):
        """Друк відомості оперативного обліку (додаток 12)."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_military_operational'
        ).report_action(self)


class HrEmployeeMilitaryOperationalReportLine(models.Model):
    _name = 'hr.employee.military.operational.report.line'
    _description = 'Запис журналу оперативного обліку'
    _order = 'date, id'

    report_id = fields.Many2one(
        'hr.employee.military.operational.report',
        required=True, ondelete='cascade', index=True,
    )
    date = fields.Date(required=True)
    employee_id = fields.Many2one('hr.employee', required=True)
    event_type = fields.Selection([
        ('hiring', 'Прийом на роботу'),
        ('dismissal', 'Звільнення'),
        ('change', 'Зміна стану'),
    ], required=True)
    description = fields.Char()


class HrEmployeeBenefitsReport(models.Model):
    """Employees with Benefits Report (Працівники з пільгами)."""
    _name = 'hr.employee.benefits.report'
    _description = 'Employees with Benefits Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    disabled_count = fields.Integer(
        string='With Disability',
        compute='_compute_employee_count',
        store=True,
    )
    chornobyl_count = fields.Integer(
        string='Chornobyl',
        compute='_compute_employee_count',
        store=True,
    )
    veteran_count = fields.Integer(
        string='Veterans',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Працівники з пільгами станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = 'Працівники з пільгами'

    @api.depends('employee_ids', 'employee_ids.disability_group',
                 'employee_ids.chornobyl_category', 'employee_ids.veteran_status')
    def _compute_employee_count(self):
        for rec in self:
            employees = rec.with_context(active_test=False).employee_ids
            rec.employee_count = len(employees)
            rec.disabled_count = len(employees.filtered(
                lambda e: e.disability_group and e.disability_group != 'none'))
            rec.chornobyl_count = len(employees.filtered(
                lambda e: e.chornobyl_category and e.chornobyl_category != 'none'))
            rec.veteran_count = len(employees.filtered(
                lambda e: e.veteran_status and e.veteran_status != 'none'))

    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(active_test=False).search([
                ('company_id', '=', rec.company_id.id),
                '|', '|', '|',
                ('disability_group', 'not in', [False, 'none']),
                ('chornobyl_category', 'not in', [False, 'none']),
                ('veteran_status', 'not in', [False, 'none']),
                ('benefit_ids', '!=', False),
            ])
            as_of = rec.date
            employees = candidates.filtered(
                lambda e: _was_employed_on(e, as_of))
            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_benefits'
        ).report_action(self)
