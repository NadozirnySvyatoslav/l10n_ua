import logging
from collections import defaultdict
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date, formatLang
from odoo.tools.sql import index_definition
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG

from .hr_version import _l10n_ua_has_rate

_logger = logging.getLogger(__name__)


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

    # Nothing stops a database from running without that index. Odoo applies it
    # through `Registry.post_constraint`, which catches the failure, sends it to
    # the `odoo.schema` logger, and queues a retry that fails on the same rows;
    # the module then loads and the upgrade reports success. The guarantee the
    # whole resolution rests on can therefore be absent, with the conflicting
    # rows still in place, and the only trace of it in a log nobody reads.
    #
    # `init` below says it where it will be seen, on every update. The Python
    # constraint further down keeps a third line from joining the two while
    # nobody has fixed them.

    def init(self):
        super().init()
        # Deferred: this writes to the chatter, and the post-init queue runs
        # once every model of the module has been through `_auto_init`.
        self.pool.post_init(self._report_duplicate_start_dates_safely)

    def _report_duplicate_start_dates_safely(self):
        """The report runs inside `load_modules`, and anything raised there
        takes the whole database down with it — every module, for every user,
        over a message about a staffing line. It is a diagnostic: it may fail
        to be produced, it may not decide whether the database comes up. The
        traceback goes to the log, where the schema errors it is about already
        are."""
        try:
            # In a savepoint, the way `Registry.post_constraint` runs the index
            # it is reporting on: a database error left uncaught would poison
            # the transaction the rest of the loading still has to write in.
            with self.env.cr.savepoint():
                self._report_duplicate_start_dates()
        except Exception:  # noqa: BLE001 - a report may not break the upgrade
            _logger.exception(
                "could not check whether two approved staffing lines of a "
                "position start on the same day; the resolution by date is "
                "unverified on this database")

    def _report_duplicate_start_dates(self):
        """Say out loud that the one-line-per-start-date guarantee is missing.

        Two approved lines of a position sharing a start date is the single
        thing the resolution cannot survive: `_resolve_batch` orders by
        `date_from desc` and takes the first, and a tie is broken by whatever
        the query plan returns that day. The same data then pays one salary
        today and another after a recalculation, with nothing to explain it.

        Those rows are also the reason the index is missing — its creation
        failed on exactly them — so the report goes by the data rather than by
        the index, and it names the lines an officer has to open. It repeats on
        every update: it is meant to stop when the rows are corrected, not when
        somebody has read it once.
        """
        index_name = self._one_approved_line_per_start_date.full_name(self)
        duplicates = self._read_group(
            [('state', '=', 'approved')],
            # `:day` is what `_read_group` demands of a date field, and on a
            # Date column `date_trunc('day', ...)` is the column itself — the
            # grouping stays the one the index is built on.
            ['company_id', 'department_id', 'job_id', 'date_from:day'],
            ['id:recordset'],
            having=[('__count', '>', 1)],
        )
        if not duplicates:
            if not index_definition(self.env.cr, index_name)[0]:
                # No conflicting row to blame, so the data is not what stopped
                # it: the creation failed on its own (a lock it could not take,
                # an index dropped by hand). Nothing is wrong yet, and nothing
                # stands in the way of it going wrong.
                _logger.warning(
                    "the unique index %s is not in the database: nothing "
                    "prevents two approved staffing lines of a position from "
                    "starting on the same day, and the line payroll reads "
                    "would then be undefined. The odoo.schema log says why "
                    "its creation did not go through.", index_name)
            return

        _logger.error(
            "%s position(s) hold several approved staffing lines starting on "
            "the same day, so the unique index %s could not be created. Which "
            "line an employee resolves to — and the salary a recalculated "
            "payslip carries — stays undefined until this is corrected: %s",
            len(duplicates), index_name,
            "; ".join(
                "%s / %s from %s: ids %s" % (
                    department.display_name, job.display_name,
                    date_from, lines.ids)
                for _company, department, job, date_from, lines in duplicates))

        for _company, _department, _job, date_from, lines in duplicates:
            # Every line of the group gets the same note: whichever one the
            # officer opens, it names the others.
            body = self.env._(
                'Several approved staffing lines of this position start on '
                '%(date)s (lines %(ids)s). Payroll reads whichever of them the '
                'database happens to return first, so the salary this position '
                'pays is undefined, and a recalculated payslip may not repeat '
                'what was paid. Correct the start dates, or set all but one '
                'back to draft.',
                date=format_date(self.env, date_from),
                ids=', '.join(str(line_id) for line_id in lines.ids))
            lines._message_log_batch({line_id: body for line_id in lines.ids})

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

    @api.depends('state', 'company_id', 'department_id', 'job_id',
                 'date_from', 'date_to')
    def _compute_filled_units(self):
        """Staff units held during this line's own period, not today.

        A position keeps a history of approved lines, each in force from its
        own date until the next one starts. Asking every one of them who holds
        the post *now* gave the 2023 line the occupancy of 2026: the number was
        right only on the line currently in force, and a staffing table printed
        for a past period carried somebody else's figures.

        The date a line is measured on mirrors `_reference_date`, which answers
        the same question from the other end, for a version:

        * a period that has closed is measured on its last day — a fact that
          does not move any more;
        * a line in force, or one that has yet to start, is measured on today
          or on the day it takes effect, whichever comes later.

        No `sudo()` here, and none is needed: the field is stored, so
        `compute_sudo` defaults to True (`odoo/orm/fields.py`, `_setup_attrs`)
        and the whole compute already runs elevated. That is also why the
        domains below state `company_id` by hand — under superuser there is no
        record rule left to keep companies apart.
        """
        countable = self.filtered(
            lambda line: line.state == 'approved' and line.company_id
            and line.department_id and line.job_id and line.date_from)
        (self - countable).filled_units = 0.0
        if not countable:
            return

        today = fields.Date.context_today(self)
        keys = {}
        for line in countable:
            date_end = line.date_end
            ref_date = date_end if date_end and date_end < today \
                else max(line.date_from, today)
            keys[line.id] = (line.company_id.id, line.department_id.id,
                             line.job_id.id, ref_date)

        occupancy = self._occupancy_batch(list(keys.values()))
        for line in countable:
            line.filled_units = occupancy.get(keys[line.id], 0.0)

    @api.depends('units', 'filled_units')
    def _compute_vacant_units(self):
        for record in self:
            record.vacant_units = max(0.0, record.units - record.filled_units)

    # === Occupancy ===
    # Who holds a position on a given date. The mirror of the resolution
    # below: that one asks which line a version falls under, this one which
    # versions fall under a line. They are not inverses of each other, and
    # must not be collapsed into one — a version whose period spans two
    # revisions of the staffing table is paid by exactly one of them, but
    # occupies both in turn.

    @api.model
    def _occupancy_batch(self, keys):
        """Staff units held, per (company, department, job, date).

        Keys carry ids, not recordsets, so they stay hashable — the same shape
        `_resolve_batch` takes. One pass serves the whole batch: the caller is
        a computed field read down a list view, where a query per line would
        be felt at once.
        """
        keys = [key for key in keys if all(key)]
        if not keys:
            return {}
        totals = dict.fromkeys(keys, 0.0)
        for source in (self._occupancy_from_versions,
                       self._occupancy_from_combinings):
            for key, rate in source(keys).items():
                totals[key] += rate
        return totals

    @api.model
    def _occupancy_from_versions(self, keys):
        """Employees holding each position on its date, read from hr.version.

        Never from `hr.employee`: `department_id`, `job_id` and `active` on the
        card are delegated to the version in force *now*
        (`hr.employee._inherits`), so they cannot answer for 2023 at all, and
        `current_version_id` behind them is only refreshed by a daily cron.

        Two queries. The first finds who ever held these positions; the second
        reads the whole timeline of those people, because which version is in
        force on a date is only known once the later ones are known too — an
        employee moved to another post in June must not still be counted on
        the old one in December.
        """
        Version = self.env['hr.version'].with_context(active_test=False)
        last_date = max(key[3] for key in keys)
        holders = Version.search([
            ('employee_id', '!=', False),
            ('company_id', 'in', list({key[0] for key in keys})),
            ('department_id', 'in', list({key[1] for key in keys})),
            ('job_id', 'in', list({key[2] for key in keys})),
            ('date_version', '<=', last_date),
        ])
        if not holders:
            return {}

        # Only the columns needed. Reading fields off a searched recordset
        # makes the ORM fetch every stored field of hr.version — over a
        # hundred of them — for every version of every employee involved.
        columns = ['employee_id', 'company_id', 'department_id', 'job_id',
                   'date_version', 'contract_date_start', 'contract_date_end',
                   'departure_date']
        if 'work_rate' in Version._fields:
            # Added by l10n_ua_hr_contract, which depends on this module and
            # not the other way round, so the column may be absent.
            columns.append('work_rate')
        employees = holders.employee_id
        rows = Version.search_read(
            [('employee_id', 'in', employees.ids),
             ('date_version', '<=', last_date)],
            columns, order='date_version, id')
        # Safety net for broken data, the same one the headcount report keeps:
        # an archived employee with no end date anywhere was archived by hand,
        # bypassing both the dismissal order and core's departure wizard. There
        # is no telling when they actually left, so they are dropped rather
        # than left occupying the post for ever.
        archived = set(self.env['hr.employee'].with_context(
            active_test=False).search([
                ('id', 'in', employees.ids), ('active', '=', False)]).ids)

        timelines = defaultdict(list)
        # A departure is a fact about the person, not about a version: it is
        # written through the employee card, so it lands on whichever version
        # was current that day and is empty on all the others. Kept as the
        # fallback for legacy dismissals that never reached
        # `contract_date_end`, the same way the headcount report does it.
        departures = {}
        for row in rows:
            employee = row['employee_id'][0]
            timelines[employee].append(row)
            departure = row['departure_date']
            if departure:
                previous = departures.get(employee)
                if not previous or departure > previous:
                    departures[employee] = departure

        wanted = set(keys)
        totals = defaultdict(float)
        for ref_date in {key[3] for key in keys}:
            for employee, timeline in timelines.items():
                in_force = None
                for row in timeline:  # ordered by date_version ascending
                    if row['date_version'] > ref_date:
                        break
                    in_force = row
                if in_force is None:
                    continue
                start = in_force['contract_date_start']
                if start and start > ref_date:
                    continue
                end = in_force['contract_date_end'] or departures.get(employee)
                if end and end < ref_date:
                    continue
                if not end and employee in archived:
                    continue
                key = (in_force['company_id'] and in_force['company_id'][0],
                       in_force['department_id'] and in_force['department_id'][0],
                       in_force['job_id'] and in_force['job_id'][0],
                       ref_date)
                if key in wanted:
                    # `work_rate` defaults to 1.0, so a falsy one is missing
                    # data rather than an unpaid post.
                    totals[key] += in_force.get('work_rate') or 1.0
        return totals

    @api.model
    def _occupancy_from_combinings(self, keys):
        """Combined posts consume their share of the unit (#149).

        Dated like everything else here, so a combination that ran in 2023 is
        counted on the 2023 line and not on today's. One gap stays: cancelling
        a combination stamps no end date on it, so a cancelled one drops out of
        every date at once rather than out of the dates after the cancellation.
        Recording that would change what `action_cancel` writes, which belongs
        to the module owning the model.
        """
        Combining = self.env.get('hr.job.combining')
        if Combining is None:
            return {}
        ref_dates = {key[3] for key in keys}
        combinings = Combining.search([
            ('company_id', 'in', list({key[0] for key in keys})),
            ('combined_department_id', 'in', list({key[1] for key in keys})),
            ('combined_job_id', 'in', list({key[2] for key in keys})),
            ('state', '=', 'active'),
            ('date_from', '<=', max(ref_dates)),
        ])

        wanted = set(keys)
        totals = defaultdict(float)
        for combining in combinings:
            for ref_date in ref_dates:
                if combining.date_from > ref_date:
                    continue
                if combining.date_to and combining.date_to < ref_date:
                    continue
                key = (combining.company_id.id,
                       combining.combined_department_id.id,
                       combining.combined_job_id.id, ref_date)
                if key in wanted:
                    totals[key] += combining.combined_rate or 0.0
        return totals

    def _positions(self):
        """The (company, department, job) triples these lines describe."""
        return {(line.company_id.id, line.department_id.id, line.job_id.id)
                for line in self}

    @api.model
    def _recompute_occupancy(self, positions):
        """Queue `filled_units` on every line of these positions.

        There is no `@api.depends` path from a staffing line to the versions
        that occupied it: `hr.job.employee_ids` reaches only the people whose
        *current* post this is, so a 2023 version belonging to somebody who has
        since moved on is invisible to the dependency graph. Whoever changes
        such a version says so here instead.

        `add_to_compute` rather than calling the compute directly. A direct
        call runs under the writer's own rights and stores what it produces,
        and this count is made of `contract_date_*`, which core keeps behind
        hr.group_hr_manager — an HR officer issuing an order would get an
        AccessError. Going through the ORM gets the `compute_sudo` a stored
        field is entitled to.
        """
        positions = {position for position in positions if all(position)}
        if not positions:
            return
        self.search([
            ('company_id', 'in', list({position[0] for position in positions})),
            ('department_id', 'in', list({position[1] for position in positions})),
            ('job_id', 'in', list({position[2] for position in positions})),
        ]).filtered(
            lambda line: (line.company_id.id, line.department_id.id,
                          line.job_id.id) in positions
        )._mark_occupancy_dirty()

    def _mark_occupancy_dirty(self):
        """Queue the occupancy pair on these lines for recomputation.

        Both fields, not `filled_units` alone: `add_to_compute` marks exactly
        what it is given, and a dependent stored field is only dragged along
        when its source is *written*. Queueing the first by itself left
        `vacant_units` to be read straight back from the column, which still
        held the figure from before.

        `date_end` is dropped from the cache in the same breath. It is not
        stored, and it depends on the sibling lines of the position rather
        than on anything of this record's own, so approving a line next to
        these ones leaves the cached value of the older one still claiming its
        period is open — and the occupancy would then be measured on today
        instead of on the day the period actually closed.
        """
        if not self:
            return
        self.invalidate_recordset(['date_end'])
        for name in ('filled_units', 'vacant_units'):
            self.env.add_to_compute(self._fields[name], self)

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

    @api.constrains('state', 'company_id', 'department_id', 'job_id',
                    'date_from')
    def _check_one_approved_line_per_start_date(self):
        """The rule of `_one_approved_line_per_start_date`, in Python.

        The index states it better — it holds against two officers approving at
        the same moment, which no Python check can. But it is also the one
        guarantee that can be missing without anybody noticing, and a database
        that came up without it would take a third conflicting line as readily
        as it took the second. Where the index is in place this never fires:
        the write reaches the database first and is refused there.
        """
        approved = self.filtered(
            lambda line: line.state == 'approved' and line.date_from)
        if not approved:
            return

        def position_start(line):
            return (line.company_id.id, line.department_id.id,
                    line.job_id.id, line.date_from)

        taken = defaultdict(list)
        # One query for the batch: a migration or an import approves lines by
        # the hundred, and this runs on every one of them.
        for line in self.search([
            ('id', 'not in', approved.ids),
            ('state', '=', 'approved'),
            ('company_id', 'in', approved.company_id.ids),
            ('department_id', 'in', approved.department_id.ids),
            ('job_id', 'in', approved.job_id.ids),
            ('date_from', 'in', approved.mapped('date_from')),
        ]):
            taken[position_start(line)].append(line)

        for line in approved:
            key = position_start(line)
            if taken[key]:
                raise ValidationError(self.env._(
                    'This position already has an approved staffing line '
                    'starting on %(date)s. Two of them leave the salary '
                    'payroll reads undefined — correct the existing line '
                    'instead of adding a second one.',
                    date=format_date(self.env, line.date_from)))
            taken[key].append(line)

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


    # Fields whose change moves a period, and therefore the date every line of
    # the position is measured on: a new approved line ends the one before it,
    # so its neighbours have to be counted again as well.
    _PERIOD_FIELDS = frozenset({
        'state', 'date_from', 'date_to',
        'company_id', 'department_id', 'job_id',
    })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        self._recompute_occupancy(lines._positions())
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
        moves_period = not self._PERIOD_FIELDS.isdisjoint(vals)
        positions = self._positions() if moves_period else set()
        result = super().write(vals)
        if moves_period:
            self._recompute_occupancy(positions | self._positions())

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
