from collections import defaultdict
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date, formatLang
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG

from .hr_version import _l10n_ua_has_rate


class HrStaffingTable(models.Model):
    _name = 'hr.staffing.table'
    _description = 'Staffing Table'
    _order = 'date_from desc, department_id, job_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, default=lambda self: self.env.company)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        required=True, index=True)
    job_id = fields.Many2one(
        'hr.job', string='Position',
        required=True, index=True)
    units = fields.Float(
        string='Staff Units', default=1.0,
        help='Number of staff units (e.g., 0.5, 1.0, 2.0)')
    filled_units = fields.Float(
        string='Filled Units', compute='_compute_filled_units', store=True)
    vacant_units = fields.Float(
        string='Vacant Units', compute='_compute_vacant_units', store=True)
    salary = fields.Monetary(
        string='Salary', currency_field='currency_id',
        required=True,
        help='Standard salary for this position')
    salary_min = fields.Monetary(
        string='Minimum Salary', currency_field='currency_id',
        help='Minimum salary for this position (salary range)')
    salary_max = fields.Monetary(
        string='Maximum Salary', currency_field='currency_id',
        help='Maximum salary for this position (salary range)')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    total_salary_fund = fields.Monetary(
        string='Total Salary Fund', currency_field='currency_id',
        compute='_compute_total_salary_fund', store=True)
    date_from = fields.Date(
        string='Effective From', required=True,
        default=fields.Date.context_today)
    # Not the end of this line's period — the end of the position itself. A
    # line runs until the next approved one for the same position starts, and
    # that needs no field: storing it would mean keeping two facts in step, and
    # every way they can fall out of step is a wrong salary. This date is for
    # the other case, the one that cannot be inferred: an order abolishing the
    # position, after which no line follows.
    date_to = fields.Date(
        string='Position Discontinued',
        help='Set only when the position itself ends and no new line follows. '
             'A line is superseded by the next approved line of the same '
             'position on its own, and needs no end date for that.')
    date_end = fields.Date(
        string='Effective Until', compute='_compute_date_end',
        help='Last day this line applies: the day before the next approved '
             'line of this position starts, or the day the position was '
             'discontinued, whichever comes first.')
    is_current = fields.Boolean(
        string='In Force', compute='_compute_is_current',
        search='_search_is_current')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)
    order_number = fields.Char(string='Order Number')
    order_date = fields.Date(string='Order Date')
    name = fields.Char(string='Name', compute='_compute_name', store=True)

    # A position holds a history of approved lines, and only one of them may
    # start on any given day.
    #
    # That is the whole rule, and it is enough. Periods cannot overlap, because
    # a line simply runs until the next one starts — there is no second date to
    # contradict the first. What the ordering cannot survive is a tie:
    # `_resolve_batch` sorts on `date_from desc` and takes the first line that
    # has started, and two approved lines sharing a date come back in whatever
    # order the query plan produces. The same data would then yield a different
    # salary tomorrow, and on a database where versions carry no wage of their
    # own and payroll falls back to the staffing table, that is a payslip.
    #
    # Only approved lines are constrained: drafts are working copies an officer
    # may prepare several of, and archived lines are outside the resolution.
    _one_approved_line_per_start_date = models.UniqueIndex(
        "(company_id, department_id, job_id, date_from) WHERE state = 'approved'",
        'This position already has an approved staffing line starting on that '
        'date. Correct the existing line instead of adding a second one.',
    )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.department_id and self.department_id.company_id \
                and self.department_id.company_id != self.company_id:
            self.department_id = False
        if self.job_id and self.job_id.company_id \
                and self.job_id.company_id != self.company_id:
            self.job_id = False

    @api.depends('department_id', 'job_id')
    def _compute_name(self):
        for record in self:
            dept = record.department_id.name or ''
            job = record.job_id.name or ''
            record.name = f"{dept} / {job}"

    @api.depends('date_from', 'date_to', 'company_id', 'department_id', 'job_id')
    def _compute_date_end(self):
        """Last day a line applies — derived, never stored.

        Mirrors what core does for a version of an employee
        (`hr.version._compute_dates`): the period ends the day before the next
        one starts, and an explicit end may only cut it shorter.
        """
        starts = defaultdict(list)
        if self:
            for line in self.search([
                    ('state', '=', 'approved'),
                    ('company_id', 'in', self.company_id.ids),
                    ('department_id', 'in', self.department_id.ids),
                    ('job_id', 'in', self.job_id.ids)]):
                starts[(
                    line.company_id.id, line.department_id.id, line.job_id.id,
                )].append(line.date_from)

        for record in self:
            key = (record.company_id.id, record.department_id.id,
                   record.job_id.id)
            following = [
                start for start in starts.get(key, ())
                if start and record.date_from and start > record.date_from
            ]
            superseded_on = min(following) - timedelta(days=1) if following else False
            if superseded_on and record.date_to:
                record.date_end = min(superseded_on, record.date_to)
            else:
                record.date_end = superseded_on or record.date_to

    @api.depends('date_from', 'date_to', 'state',
                 'company_id', 'department_id', 'job_id')
    def _compute_is_current(self):
        """Whether this is the line payroll would read today.

        Asked of `_resolve_batch`, not derived a second time from `date_end`.
        The same question answered by two independent derivations drifts, and it
        already had: the search method used to disagree with the resolution
        about a position that had been discontinued, and offered the line it
        superseded years earlier. One rule now answers in all three places.

        The comparison goes through `_origin` so that a line being edited in a
        form still reports the state of the record it stands for.
        """
        today = fields.Date.context_today(self)
        keys = {
            record.id: (record.company_id.id, record.department_id.id,
                        record.job_id.id, today)
            for record in self
        }
        resolved = self._resolve_batch(list(keys.values()))
        for record in self:
            in_force = resolved.get(keys[record.id])
            record.is_current = bool(in_force) and in_force == record._origin

    def _search_is_current(self, operator, value):
        """Searchable so the list can be filtered down to what is in force.

        Not expressible as a plain domain: whether a line still applies depends
        on whether a later one has started, which is a fact about its siblings.
        So the ids are worked out here, the way core does for `date_start` and
        `date_end` on a version.

        The answer comes from `_resolve_batch` rather than from a second
        implementation of the same rule. A search that decided for itself which
        line is in force would drift from the one payroll reads — and it did:
        for a discontinued position the resolution correctly returns nothing
        while a hand-written search happily offered the line that had been
        superseded years before.
        """
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError(
                'Only "=" and "!=" against a boolean are supported.')

        today = fields.Date.context_today(self)
        positions = self._read_group(
            [('state', '=', 'approved')],
            groupby=['company_id', 'department_id', 'job_id'])
        resolved = self._resolve_batch([
            (company.id, department.id, job.id, today)
            for company, department, job in positions
        ])

        matches = (operator == '=') == value
        return [('id', 'in' if matches else 'not in',
                 [line.id for line in resolved.values()])]

    @api.depends('units', 'salary')
    def _compute_total_salary_fund(self):
        for record in self:
            record.total_salary_fund = record.units * record.salary

    @api.depends(
        'department_id', 
        'job_id', 
        'state',
        'job_id.employee_ids',
        'job_id.employee_ids.department_id',
        'job_id.employee_ids.active',
        'job_id.employee_ids.current_version_id'
    )
    def _compute_filled_units(self):
        for record in self:
            if record.state == 'approved' and record.department_id and record.job_id:
                employees = self.env['hr.employee'].search([
                    ('department_id', '=', record.department_id.id),
                    ('job_id', '=', record.job_id.id),
                    ('active', '=', True),
                ])
                # Sum work_rate for all employees (0.5 for part-time, 1.0 for full-time)
                total_rate = 0.0
                for emp in employees:
                    version = emp.current_version_id
                    # `work_rate` додає l10n_ua_hr_contract, який залежить
                    # від цього модуля, а не навпаки — тож поля може не бути.
                    if version and 'work_rate' in version._fields and version.work_rate:
                        total_rate += version.work_rate
                    else:
                        total_rate += 1.0  # Default full-time
                # Суміщення (сумісництво) споживає свою частку штатної одиниці
                # цієї посади нарівні з основними працівниками (#149).
                Combining = self.env.get('hr.job.combining')
                if Combining is not None:
                    combinings = Combining.search([
                        ('combined_department_id', '=', record.department_id.id),
                        ('combined_job_id', '=', record.job_id.id),
                        ('state', '=', 'active'),
                    ])
                    total_rate += sum(
                        c.combined_rate or 0.0 for c in combinings)
                record.filled_units = total_rate
            else:
                record.filled_units = 0.0

    @api.depends('units', 'filled_units')
    def _compute_vacant_units(self):
        for record in self:
            record.vacant_units = max(0.0, record.units - record.filled_units)

    # === Resolution ===
    # A position is identified by (company, department, job); which line of the
    # staffing table applies is then a question of date. Everything that needs
    # "the staffing line of this employee" goes through here, so the rule lives
    # in one place.

    @api.model
    def _reference_date(self, own_date, contract_start, contract_end,
                        sibling_dates, today):
        """Date a position is read against: the end of its period, else today.

        Takes plain values rather than a record, because two models ask the
        question: `hr.version` for a version of the history, and `hr.employee`
        for the card, where the answer has to follow fields still being edited.
        One rule, one place — the card and the version list can never disagree.

        Mirrors what core computes as `date_start` / `date_end`
        (`hr.version._compute_dates`) instead of reading those fields: they are
        computed one record at a time with a search each, which a batched
        compute cannot afford.

        :param own_date: `date_version` of the version in question
        :param sibling_dates: `date_version` of that employee's other versions
        """
        own_date = own_date or today
        start = own_date
        if contract_start and contract_start > start:
            start = contract_start
        following = [date for date in sibling_dates if date and date > own_date]
        end = min(following) - timedelta(days=1) if following else False
        if end and contract_end:
            end = min(end, contract_end)
        elif not end:
            end = contract_end
        # A version dated in the future is read against the day it takes
        # effect: by then the staffing table may well be a different one.
        return end or max(start, today)

    @api.model
    def _resolve(self, company, department, job, ref_date):
        """Approved line in force for this position on `ref_date`.

        Returns an empty recordset when the position is not covered by the
        staffing table — a legitimate state, not an error: keeping a staffing
        table is a choice, and civil-law contracts never occupy a staff unit.
        """
        if not (company and department and job and ref_date):
            return self.browse()
        key = (company.id, department.id, job.id, ref_date)
        return self._resolve_batch([key]).get(key, self.browse())

    @api.model
    def _resolve_batch(self, keys):
        """Resolve many positions at once: {(company, department, job, date): line}.

        Keys carry ids, not recordsets, so they stay hashable. One query serves
        the whole batch — the callers are computed fields read over a list view,
        where a query per record would be felt immediately.
        """
        keys = [key for key in keys if all(key)]
        if not keys:
            return {}
        lines = self.search([
            ('company_id', 'in', list({key[0] for key in keys})),
            ('department_id', 'in', list({key[1] for key in keys})),
            ('job_id', 'in', list({key[2] for key in keys})),
            ('state', '=', 'approved'),
        ], order='date_from desc')

        by_position = defaultdict(list)
        for line in lines:
            by_position[(
                line.company_id.id, line.department_id.id, line.job_id.id,
            )].append(line)

        resolved = {}
        for key in keys:
            ref_date = key[3]
            for line in by_position.get(key[:3], ()):
                if line.date_from > ref_date:
                    # Not started yet on that date — an earlier line applies.
                    continue
                # Ordered by start descending, so this is the line that had
                # taken over by then, and the search stops here either way: if
                # the position was discontinued before this date, no older line
                # comes back to life — it was superseded long before.
                if not line.date_to or line.date_to >= ref_date:
                    resolved[key] = line
                break
        return resolved

    def _salary_in_company_currency(self, date=None):
        """This line's salary, in the currency of the company that keeps it.

        The staffing table names a currency of its own, and it is not the one
        a version's wage is denominated in. Payroll reads this figure as a
        fallback for a version that carries no wage — which is exactly the case
        where the version's currency says nothing about this money — so putting
        it through the version's rate turns a position of 20 000 UAH into
        830 000. The line answers for its own money, on the date it is asked
        about, because the rate moves.
        """
        self.ensure_one()
        salary = self.salary or 0.0
        company = self.company_id or self.env.company
        currency = self.currency_id
        company_currency = company.currency_id
        if not salary or not currency or not company_currency \
                or currency == company_currency:
            return salary

        date = date or fields.Date.context_today(self)
        if not _l10n_ua_has_rate(self.env, currency, company, date):
            raise UserError(self.env._(
                'The staffing line "%(position)s" states its salary in '
                '%(currency)s, and no rate for that currency is on file for '
                '%(date)s. Without one the salary would enter payroll as '
                'though it were hryvnia. Add the rate to the currency table.',
                position=self.name or '',
                currency=currency.name,
                date=format_date(self.env, date)))

        # round=False for the reason it is false everywhere else here: a rate
        # squeezed to the kopiyka costs two hryvnia on every thousand.
        return currency._convert(
            salary, company_currency, company, date, round=False)

    @api.constrains('units')
    def _check_units(self):
        for record in self:
            if record.units <= 0:
                raise ValidationError('Staff units must be greater than 0!')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """A position cannot be abolished before the line that describes it
        starts. `date_to` no longer means the end of this line's period — that
        is derived — so the message names what the field now is."""
        for record in self:
            if record.date_to and record.date_from > record.date_to:
                raise ValidationError(self.env._(
                    'A position cannot be discontinued on %(discontinued)s, '
                    'before the staffing line describing it starts on '
                    '%(start)s.',
                    discontinued=format_date(self.env, record.date_to),
                    start=format_date(self.env, record.date_from)))

    @api.constrains('salary', 'salary_min', 'salary_max')
    def _check_salary_range(self):
        for record in self:
            if record.salary_min and record.salary_max:
                if record.salary_min > record.salary_max:
                    raise ValidationError('Minimum salary cannot exceed maximum salary!')
            if record.salary:
                if record.salary_min and record.salary < record.salary_min:
                    raise ValidationError('Standard salary cannot be below minimum salary!')
                if record.salary_max and record.salary > record.salary_max:
                    raise ValidationError('Standard salary cannot exceed maximum salary!')


    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._warn_retroactive_change()
        lines._warn_discontinued_while_occupied()
        return lines

    def write(self, vals):
        today = fields.Date.context_today(self)
        # Whether a change reached the past is a question about the pair of
        # values, and only one of them survives the write. That matters for a
        # single field: moving a start date forward takes a period out of the
        # history exactly as surely as moving it back puts one in. For anything
        # else the record after the write says all there is to say, so nothing
        # is read here unless the start is what moves.
        was_in_force = {
            record.id for record in self
            if record.state == 'approved'
            and record.date_from and record.date_from < today
        } if 'date_from' in vals else ()
        result = super().write(vals)

        # Only the fields that decide a salary. Staff units and the range do
        # not reach a payslip — warning about them would say something untrue
        # and teach the officer to skip the message that matters.
        retroactive = bool(vals.keys() & {'state', 'date_from', 'salary'})
        if 'date_to' in vals and not retroactive:
            # Closing a position ahead of time changes nothing that has already
            # been calculated. Closing it in the past cuts history short, and
            # that is worth a word.
            closing = fields.Date.to_date(vals['date_to'])
            retroactive = bool(closing and closing < today)
        if retroactive:
            self._warn_retroactive_change(was_in_force)
        if vals.keys() & {'state', 'date_to'}:
            self._warn_discontinued_while_occupied()
        return result

    def unlink(self):
        """Same door as archiving, and it must be shut the same way.

        Deleting an approved line is worse than archiving one: the record goes,
        and with it the chatter that would have explained the change. Every
        recalculation of those months then produces a different figure — or
        none at all — with nothing anywhere to say why.

        Uninstalling the module is the exception, and it has to be: the demo
        data ships approved lines with xml_ids, and removing the module removes
        them through the ORM. Refusing there would leave the module impossible
        to uninstall — a rule about protecting payroll history has nothing to
        say about a database that is discarding the feature entirely.
        """
        approved = self.filtered(lambda line: line.state == 'approved')
        if approved and not self.env.context.get(MODULE_UNINSTALL_FLAG):
            raise UserError(self.env._(
                'An approved staffing line cannot be deleted: payslips are '
                'calculated from it, and removing it would change what every '
                'recalculation of those periods produces — leaving nothing '
                'behind to explain why. Use "Set to Draft" first if the line '
                'was approved by mistake.'))
        return super().unlink()

    def _warn_discontinued_while_occupied(self):
        """Note when a position is closed while people still hold it.

        Refusing would be wrong: the order abolishing a position is signed
        before anybody is moved, and a system has no business rejecting an
        order. But past that date the staffing table answers nothing for this
        position, and where a version carries no wage of its own — which is the
        rule rather than the exception here — the answer payroll gets is zero.

        The contradiction is already in the record: `filled_units` counts the
        people who hold the position. Saying it out loud is the least the model
        can do before somebody is paid nothing.
        """
        if not self.env.registry.ready:
            return

        for record in self:
            if record.state != 'approved' or not record.date_to:
                continue
            if record.filled_units <= 0:
                continue
            record._message_log(body=self.env._(
                'This position is discontinued on %(date)s while %(units)s '
                'staff unit(s) are still filled. From that date the staffing '
                'table has no answer for it, and an employee whose wage comes '
                'from the table is calculated at zero. Move them before then, '
                'or lift the date.',
                date=format_date(self.env, record.date_to),
                units=formatLang(self.env, record.filled_units),
            ))

    def _warn_retroactive_change(self, was_in_force=()):
        """Note in the line's chatter when an approved line already in force is
        touched, or approved with a start date in the past.

        Signing an order late is ordinary practice, so this refuses nothing.
        But a line that already applies is what payroll reads: changing it, or
        back-dating a new one, silently changes what every recalculation of
        those months will produce. That deserves a trace with a date on it —
        not on the employee, because a position may carry a dozen of them, but
        here, where an auditor comes looking.

        Silent during an install or upgrade: a migration writing staffing lines
        in bulk is not somebody making a decision today.
        """
        if not self.env.registry.ready:
            return

        today = fields.Date.context_today(self)
        for record in self:
            if record.state != 'approved':
                continue
            if record.date_from and record.date_from < today:
                record._message_log(body=self.env._(
                    'This staffing line applies from %(date)s, which is '
                    'already past. Any payslip recalculated for a period from '
                    'that date will use it — let payroll know before that '
                    'happens.',
                    date=format_date(self.env, record.date_from),
                ))
            elif record.id in was_in_force:
                # It used to cover months that are already closed, and does
                # not any more.
                record._message_log(body=self.env._(
                    'This line no longer covers the periods it did: it now '
                    'starts on %(date)s. A payslip recalculated for a month it '
                    'used to cover falls through to an earlier line, or to '
                    'nothing at all.',
                    date=format_date(self.env, record.date_from),
                ))

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_archive(self):
        """Discard a working copy. Not a way to retire an approved line.

        An approved line is the record payroll reads, and the resolution only
        looks at approved ones. Archiving the line in force would therefore
        hand the position back to the period before it — the salary would drop
        to the previous figure, quietly, with no error and nothing in the
        chatter to explain it. Archiving an older approved line is no better:
        it takes that period out of the history, and every payslip recalculated
        for those months changes.

        The two things an officer actually wants are elsewhere. An approval
        made by mistake is undone with "Set to Draft" — the previous line comes
        back into force by itself. A position that has genuinely ceased to
        exist is closed with `date_to`.
        """
        wrong_state = self.filtered(lambda line: line.state == 'approved')
        if wrong_state:
            raise UserError(self.env._(
                'An approved staffing line cannot be archived: it is what '
                'payslips are calculated from, and removing it would quietly '
                'return the position to the salary of the period before. Use '
                '"Set to Draft" to undo an approval, or fill in "Position '
                'Discontinued" if the position itself has ended.'))
        self.write({'state': 'archived'})

    def action_draft(self):
        """Undo the last approval — not one from the middle of the history.

        For the line currently in force this is the officer's way back: the
        previous period simply applies again. For a line that has already been
        superseded it is something else entirely — the period disappears from
        the resolution, and every payslip recalculated for those months falls
        through to an older line, or to nothing at all. That is the same damage
        archiving and deleting are refused for, through a button whose name
        promises the opposite.
        """
        for record in self.filtered(lambda line: line.state == 'approved'):
            successor = self.search([
                ('id', '!=', record.id),
                ('state', '=', 'approved'),
                ('company_id', '=', record.company_id.id),
                ('department_id', '=', record.department_id.id),
                ('job_id', '=', record.job_id.id),
                ('date_from', '>', record.date_from),
            ], order='date_from', limit=1)
            if successor:
                raise UserError(self.env._(
                    'This line has already been superseded by the approved '
                    'line of %(date)s, so it is history: the payslips of its '
                    'period are calculated from it. Undo the later approval '
                    'first, if that is what you meant.',
                    date=format_date(self.env, successor.date_from)))
        self.write({'state': 'draft'})
