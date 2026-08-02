from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

# Native private (actual) address field -> our registration address field.
# private_* lives on hr.version, registration_* on hr.employee; hr_version.py
# reuses this map to keep both sides in sync from either direction.
REGISTRATION_ADDRESS_MAP = {
    'private_street': 'registration_street',
    'private_street2': 'registration_street2',
    'private_city': 'registration_city',
    'private_zip': 'registration_zip',
    'private_state_id': 'registration_region_id',
}
REGISTRATION_SYNC_TRIGGERS = set(REGISTRATION_ADDRESS_MAP) | {'registration_same_as_actual'}


def _join_address_parts(parts):
    """Join non-empty address components into a single printable line."""
    return ', '.join(part for part in parts if part)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # === Personal Documents ===
    employee_number = fields.Char(
        string='Personnel Number',
        copy=False,
        help='Personnel number of the employee according to Ukrainian legislation (Табельний номер)')

    def action_generate_employee_number(self):
        """Generate next personnel number from the sequence."""
        for employee in self:
            if not employee.employee_number:
                employee.employee_number = self.env['ir.sequence'].next_by_code('hr.employee.number')

    # RNOKPP is Ukrainian-specific, different from Odoo's identification_id
    rnokpp = fields.Char(
        string='RNOKPP (IPN)', size=10,
        help='Registration Number of the Taxpayer Account Card (Individual Tax Number)')

    # Document type and Ukrainian-specific fields
    document_type = fields.Selection([
        ('passport', 'Passport (old format)'),
        ('id_card', 'ID Card'),
        ('other', 'Other'),
    ], string='Document Type', default='id_card')
    passport_series = fields.Char(string='Passport Series', size=2,
                                   help='For old format passports only')
    # Use Odoo core passport_id field (via hr.version)
    # passport_number - REMOVED, use passport_id from core
    passport_issued_by = fields.Char(string='Issued By', size=100)
    passport_issued_date = fields.Date(string='Issue Date')
    # passport_valid_until - REMOVED, use passport_expiration_date from core
    passport_record_number = fields.Char(string='Record Number', size=14,
                                          help='Unique record number in the register (for ID cards)')

    # === Registration Address (Прописка) ===
    # The native private_* block (on hr.version) is the master address; this
    # block mirrors it one-to-one, minus the country: a прописка is by
    # definition a domestic record, hence the UA-only domain on the region and
    # the absence of a registration country field.
    registration_same_as_actual = fields.Boolean(
        string='Registration Address Same as Private Address',
        help='When checked, registration address fields are automatically copied from native Odoo private_* fields.')

    registration_street = fields.Char(string='Registration Street')
    registration_street2 = fields.Char(string='Registration Street 2')
    registration_region_id = fields.Many2one(
        'res.country.state', string='Registration Region',
        domain="[('country_id.code', '=', 'UA')]")
    registration_city = fields.Char(string='Registration City')
    # No size limit: private_zip is unbounded, and a narrower column here would
    # silently truncate whatever it mirrors.
    registration_zip = fields.Char(string='Registration ZIP')

    # === Education ===
    # Use Odoo core fields: study_school (institution), study_field (specialty), certificate (level)
    # education_institution - REMOVED, use study_school from core
    # education_specialty - REMOVED, use study_field from core
    # Keep education_level_id as Many2one for more detailed Ukrainian education levels
    education_level_id = fields.Many2one('hr.education.level', string='Education Level (UA)',
                                          help='Detailed Ukrainian education level classification')
    # Ukrainian-specific diploma details
    diploma_series = fields.Char(string='Diploma Series')
    diploma_number = fields.Char(string='Diploma Number')
    diploma_date = fields.Date(string='Diploma Date')

    # === Military Accounting ===
    military_accounting_applicable = fields.Boolean(
        string='Підлягає військовому обліку',
        compute='_compute_military_accounting_applicable',
        help='Військовий облік ведеться лише щодо громадян України '
             '(ст. 1 Закону № 2232-XII «Про військовий обов\'язок і військову '
             'службу»). Обчислюється з громадянства — штатного поля '
             '«Nationality (Country)» на версії трудового договору. '
             'Незаповнене громадянство вважається українським: у більшості '
             'карток його не вносять, і ховати блок від усіх було б гірше, '
             'ніж показати його зайвий раз.')
    military_status = fields.Selection([
        ('liable', 'Liable for Military Service'),
        ('reserved', 'Reserved'),
        ('exempt', 'Exempt'),
        ('not_applicable', 'Not Applicable'),
    ], string='Military Status (legacy)', default='not_applicable',
        help='Legacy field — kept for backward compatibility. '
             'Use military_register_category for the official ПКМУ № 1487 categorization.')
    military_register_category = fields.Selection([
        ('conscript', 'Призовник'),
        ('liable', 'Військовозобов\'язаний'),
        ('reservist', 'Резервіст'),
        ('not_applicable', 'Не підлягає обліку'),
    ], string='Категорія військового обліку',
        default='not_applicable',
        tracking=True,
        help='Категорія військового обліку за ПКМУ № 1487 від 30.12.2022. '
             'Призовник — особа призовного віку, не пройшла строкову службу. '
             'Військовозобов\'язаний — у запасі. '
             'Резервіст — добровільний оперативний резерв.')
    military_category = fields.Selection([
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('removed', 'Removed from Register'),
    ], string='Military Category')
    military_rank_id = fields.Many2one('hr.military.rank', string='Military Rank')
    military_specialty = fields.Char(string='Military Specialty (VOS)',
                                      help='Military Occupational Specialty')
    military_fitness = fields.Selection([
        ('fit', 'Придатний'),
        ('fit_support', 'Придатний до служби в частинах забезпечення'),
        ('temp_unfit', 'Тимчасово непридатний'),
        ('unfit', 'Непридатний'),
    ], string='Придатність до служби',
        tracking=True,
        help='Категорії за Законом № 3621-IX від 04.05.2024. '
             'Статус «обмежено придатний» (legacy «limited») скасовано — '
             'мігруються в «Тимчасово непридатний».')
    military_medical_category = fields.Selection([
        ('A', 'А — придатний без обмежень'),
        ('B', 'Б — придатний з незначними обмеженнями'),
        ('V', 'В — обмежено придатний (медичний висновок)'),
        ('G', 'Г — тимчасово непридатний'),
        ('D', 'Д — непридатний'),
    ], string='Медична категорія (ВЛК)',
        help='Категорія за Наказом Міністерства оборони України № 402 — '
             'Положення про військово-лікарську експертизу, розклад хвороб. '
             'Категорія «В» зберігається як медичний висновок, навіть якщо у '
             '`military_fitness` обрано іншу категорію придатності.')
    military_mlk_retest_date = fields.Date(
        string='Дата повторного ВЛК',
        help='Запланована дата повторного проходження військово-лікарської комісії '
             '(Закон № 4235-IX про продовження строку повторної ВЛК до 05.06.2025). '
             'За 14 днів до цієї дати створюється activity для HR.')
    military_mlk_retest_due_soon = fields.Boolean(
        string='ВЛК скоро',
        compute='_compute_military_mlk_retest_due_soon',
        store=True,
        help='True, якщо повторна ВЛК заплановано протягом наступних 14 днів. '
             'Оновлюється щоденним cron-ом.')
    military_document_number = fields.Char(string='Military Document Number')
    military_tcc_id = fields.Many2one('hr.military.tcc', string='TCC',
                                       help='Territorial Recruitment Center')
    military_reservation = fields.Boolean(string='Reserved (Booking)')
    military_reservation_until = fields.Date(string='Reserved Until')
    military_reservation_expired = fields.Boolean(
        string='Reservation Expired',
        compute='_compute_military_reservation_expired',
        store=True,
        help='True when reservation end date has passed. Recomputed daily by cron — '
             'flags employees whose military booking must be renewed (CMU Resolution 1608).')
    military_reservplus_id = fields.Char(string='Reserv+ ID',
                                          help='Ідентифікатор у системі Резерв+')

    # === Benefits ===
    benefit_ids = fields.Many2many('hr.employee.benefit', string='Benefits')
    disability_group = fields.Selection([
        ('1', 'Group I'),
        ('2', 'Group II'),
        ('3', 'Group III'),
        ('none', 'None'),
    ], string='Disability Group', default='none')
    disability_reason = fields.Char(string='Disability Reason')
    disability_document = fields.Char(string='MSEC Document',
                                       help='Medical-Social Expert Commission document')
    disability_date_from = fields.Date(string='Disability From')
    disability_date_to = fields.Date(string='Disability Until')
    chornobyl_category = fields.Selection([
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('3', 'Category 3'),
        ('4', 'Category 4'),
        ('none', 'None'),
    ], string='Chornobyl Category', default='none')
    veteran_status = fields.Selection([
        ('combat', 'Combat Veteran'),
        ('war', 'War Veteran'),
        ('labor', 'Labor Veteran'),
        ('none', 'None'),
    ], string='Veteran Status', default='none')

    # === Family ===
    # Use Odoo core fields: marital (status), spouse_complete_name, spouse_birthdate, children (count)
    # marital_status_ua - REMOVED, use marital from core
    # spouse_name - REMOVED, use spouse_complete_name from core
    # Ukrainian-specific: spouse tax ID
    spouse_rnokpp = fields.Char(string='Spouse RNOKPP', size=10)
    # Detailed children records (Odoo core only has count)
    children_ids = fields.One2many('hr.employee.child', 'employee_id', string='Children')
    children_count = fields.Integer(string='Children Count', compute='_compute_children_count', store=True)
    dependents_count = fields.Integer(string='Dependents Count', compute='_compute_dependents_count', store=True,
                                       help='Children under 18, or students (up to 23), or disabled children of any age — PSP-eligible.')
    is_single_parent = fields.Boolean(
        string='Single Parent',
        groups='l10n_ua_hr_base.group_hr_ua_officer',
        help='Sole carer of dependent children. Used by payroll for elevated PSP (150% of base amount). '
             'Зміна цього поля захищена групою HR Officer — впливає на розрахунок ПДФО, '
             'тому звичайний користувач не повинен мати змогу його редагувати.')

    # === Work Experience ===
    hire_date = fields.Date(
        string='Hire Date', compute='_compute_hire_date',
        store=True, readonly=False, tracking=True,
        help='Employee hire date. Derived from the contract versions '
             '(hr.version.contract_date_start): the start of the current '
             'continuous employment spell. Correct it on the contract version, '
             'not here — the field stays writable for data imports only.')
    work_experience_total = fields.Float(string='Total Work Experience (years)',
                                          help='Total work experience in years')
    work_experience_company = fields.Float(string='Company Experience (years)',
                                            compute='_compute_work_experience_company')
    insurance_experience = fields.Float(string='Insurance Experience (years)',
                                         help='Insurance experience for sick leave calculation')
    # === Bank ===
    # Use Odoo core field: bank_account_ids (several accounts, salary
    # distribution, tracking, and a domain tying the account to the
    # employee's own work contact)
    # bank_account_id - REMOVED, use bank_account_ids from core

    # === Related fields from hr.job (readonly) ===
    job_kp_code = fields.Char(
        string='KP Code', related='job_id.kp_code', readonly=True, store=True,
        help='Код професії за Класифікатором професій ДК 003:2010')
    job_kp_name = fields.Char(
        string='KP Name', related='job_id.kp_name', readonly=True, store=True,
        help='Назва професії за Класифікатором професій')
    job_work_conditions = fields.Selection(
        related='job_id.work_conditions', readonly=True, store=False,
        string='Work Conditions')
    job_hazard_class = fields.Selection(
        related='job_id.hazard_class', readonly=True, store=False,
        string='Hazard Class')
    job_currency_id = fields.Many2one(
        related='job_id.currency_id', readonly=True, store=False,
        string='Job Currency')
    job_min_salary = fields.Monetary(
        related='job_id.min_salary', readonly=True, store=False,
        currency_field='job_currency_id', string='Min Salary')
    job_max_salary = fields.Monetary(
        related='job_id.max_salary', readonly=True, store=False,
        currency_field='job_currency_id', string='Max Salary')

    @api.constrains('employee_number', 'company_id')
    def _check_unique_employee_number(self):
        for employee in self:
            if employee.employee_number:
                # Search for duplicates within the same company
                duplicate = self.search([
                    ('id', '!=', employee.id),
                    ('employee_number', '=', employee.employee_number),
                    ('company_id', '=', employee.company_id.id)
                ], limit=1)
                
                if duplicate:
                    raise ValidationError(_(
                        "Табельний номер '%s' вже використовується для співробітника %s в цій компанії. "
                        "Табельні номери мають бути унікальними."
                    ) % (employee.employee_number, duplicate.name))

    @api.depends('children_ids')
    def _compute_children_count(self):
        for employee in self:
            employee.children_count = len(employee.children_ids)

    @api.depends('children_ids', 'children_ids.age', 'children_ids.is_student',
                  'children_ids.is_disabled')
    def _compute_dependents_count(self):
        for employee in self:
            employee.dependents_count = len(employee.children_ids.filtered(
                lambda c: c.age < 18 or c.is_student or c.is_disabled))

    @api.depends('country_id')
    def _compute_military_accounting_applicable(self):
        """Military accounting covers Ukrainian citizens only.

        The nationality lives on hr.version (core `country_id`, "Nationality
        (Country)"), so no citizenship field of our own is needed. An empty
        nationality counts as Ukrainian — the field is rarely filled in, and
        hiding the block from every such card would be worse than showing it
        once too often.
        """
        for employee in self:
            country = employee.country_id
            employee.military_accounting_applicable = (
                not country or country.code == 'UA')

    @api.constrains('military_register_category')
    def _check_military_accounting_citizenship(self):
        """A foreign national cannot be put on the military register.

        Only the military side is watched here. The nationality is stored on
        hr.version, so writing `country_id` on the employee never reaches an
        hr.employee constraint — hr.version carries the mirror check (see
        `hr_version._check_ua_military_citizenship`).
        """
        self._assert_military_matches_citizenship()

    def _assert_military_matches_citizenship(self):
        for employee in self:
            if (employee.military_register_category
                    and employee.military_register_category != 'not_applicable'
                    and not employee.military_accounting_applicable):
                raise ValidationError(_(
                    'Military accounting applies to citizens of Ukraine only '
                    '(art. 1 of Law No 2232-XII). %(employee)s has the '
                    'nationality %(country)s — clear the military register '
                    'category or correct the nationality.',
                    employee=employee.name,
                    country=employee.country_id.name,
                ))

    @api.depends('military_reservation', 'military_reservation_until')
    def _compute_military_reservation_expired(self):
        today = date.today()
        for employee in self:
            employee.military_reservation_expired = bool(
                employee.military_reservation
                and employee.military_reservation_until
                and employee.military_reservation_until < today
            )

    @api.depends('military_mlk_retest_date')
    def _compute_military_mlk_retest_due_soon(self):
        today = date.today()
        for employee in self:
            if not employee.military_mlk_retest_date:
                employee.military_mlk_retest_due_soon = False
                continue
            delta = (employee.military_mlk_retest_date - today).days
            employee.military_mlk_retest_due_soon = 0 <= delta <= 14

    @api.model
    def _cron_check_military_reservation_expired(self):
        """Daily cron: flag employees whose reservation end date has just passed.

        The stored compute depends on (military_reservation, military_reservation_until)
        and won't refire on calendar advance, so the cron writes the flag directly.
        For newly-expired (False → True transition), notifies HR officers via email
        and activity (ПКМУ № 1608 — обов'язок роботодавця контролювати ліміти).
        """
        today = date.today()
        stale = self.search([
            ('military_reservation', '=', True),
            ('military_reservation_until', '!=', False),
            ('military_reservation_until', '<', today),
            ('military_reservation_expired', '=', False),
        ])
        if not stale:
            return
        stale.write({'military_reservation_expired': True})
        # Notify HR officers about newly-expired reservations
        stale._notify_military_reservation_expired()

    def _notify_military_reservation_expired(self):
        """Post chatter message + schedule activity for HR officers when reservation expires.

        Uses mail.template for body rendering, then message_post with HR partners
        in partner_ids — this triggers emails to HR officers via mail thread.
        """
        template = self.env.ref(
            'l10n_ua_hr_base.mail_template_military_reservation_expired',
            raise_if_not_found=False,
        )
        activity_type = self.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False,
        )
        hr_group = self.env.ref(
            'l10n_ua_hr_base.group_hr_ua_officer', raise_if_not_found=False,
        )
        hr_users = hr_group.user_ids if hr_group else self.env['res.users']
        hr_partners = hr_users.partner_id

        for employee in self:
            # Render body from template if available, else use a default body
            body_html = _('<p>⚠️ Військове бронювання працівника <strong>%s</strong> '
                          'прострочено (до %s). Згідно з ПКМУ № 1608 потрібне '
                          'переоформлення або зняття з обліку.</p>',
                          employee.name, employee.military_reservation_until)
            if template:
                try:
                    rendered = template._render_field('body_html', [employee.id])
                    body_html = rendered.get(employee.id) or body_html
                except Exception:
                    pass
            # Post in employee chatter and notify HR officers via partner_ids
            employee.message_post(
                body=body_html,
                subtype_xmlid='mail.mt_comment',
                partner_ids=hr_partners.ids if hr_partners else [],
            )
            # Activity for the first HR officer (head-of-line)
            if activity_type and hr_users:
                manager = hr_users[0]
                existing = employee.activity_ids.filtered(
                    lambda a: a.activity_type_id == activity_type
                    and 'бронювання' in (a.summary or '').lower()
                )
                if not existing:
                    employee.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=manager.id,
                        summary=_('Прострочене військове бронювання'),
                        note=_('Бронювання працівника %s прострочено '
                               '(до %s). Оформіть нове або зніміть з обліку.',
                               employee.name,
                               employee.military_reservation_until),
                    )

    @api.model
    def _cron_check_military_mlk_retest(self):
        """Daily cron: flag employees whose ВЛК retest date is within 14 days.

        The stored compute depends on military_mlk_retest_date only,
        so without daily refresh the boolean would stay stale.
        Also schedules a mail.activity for HR officers on newly-due records.
        """
        today = date.today()
        in_14_days = today + timedelta(days=14)
        due_employees = self.search([
            ('military_mlk_retest_date', '>=', today),
            ('military_mlk_retest_date', '<=', in_14_days),
        ])
        # Refresh the boolean for the in-window set
        due_employees._compute_military_mlk_retest_due_soon()
        # Activity scheduling
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        for emp in due_employees:
            existing = emp.activity_ids.filtered(
                lambda a: a.activity_type_id == activity_type
                and 'ВЛК' in (a.summary or '')
            )
            if existing:
                continue
            emp.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=emp.military_mlk_retest_date,
                summary='Повторна ВЛК',
                note=(f'У співробітника <b>{emp.name}</b> заплановано повторну '
                      f'військово-лікарську комісію на {emp.military_mlk_retest_date}. '
                      'Узгодьте з ТЦК.'),
            )

    # A gap of four days or more between two contract periods starts a new
    # employment spell — the same threshold core uses in
    # `hr.employee._get_first_version_date()`.
    UA_EMPLOYMENT_GAP_DAYS = 4

    def _get_ua_first_contract_date(self):
        """Start of the CURRENT continuous employment spell (hr.version).

        Follows the gap rule of the core helper `_get_first_version_date()`,
        but reads `contract_date_start` / `contract_date_end` instead of the
        computed `date_start`. Core falls back to `date_version` when a
        version carries no contract period, which would report a hire date
        for every employee — including legacy records imported without any
        contract data, whose manual `hire_date` must survive.

        Returns False while no version carries a contract start date.
        """
        self.ensure_one()
        versions = self.with_context(active_test=False).version_ids.filtered('contract_date_start')
        if not versions:
            return False
        versions = versions.sorted('contract_date_start', reverse=True)
        anchor = versions[0].contract_date_start
        for previous in versions[1:]:
            # An open-ended previous period never opens a gap, exactly as core
            # does with its date(2100, 1, 1) sentinel.
            gap = (anchor - (previous.contract_date_end or date(2100, 1, 1))).days
            if gap >= self.UA_EMPLOYMENT_GAP_DAYS:
                break
            anchor = previous.contract_date_start
        return anchor

    @api.depends('version_ids.contract_date_start', 'version_ids.contract_date_end',
                 'version_ids.date_version', 'version_ids.active')
    def _compute_hire_date(self):
        """Hire date derived from the contract versions (hr.version).

        The contract versions are the single source of truth. The start of the
        CURRENT continuous employment spell (a gap of 4 days or more between
        versions opens a new one) matches Ukrainian practice: a rehire moves
        the vacation work-year anchor, an uninterrupted transfer does not.

        A manual value is NOT overwritten while no version carries a
        contract_date_start (legacy data import) — the same pattern core uses
        for `hr.employee.legal_name`.

        sudo() is required: `contract_date_start` is restricted to
        groups="hr.group_hr_manager".
        """
        for employee in self:
            native = employee.sudo()._get_ua_first_contract_date()
            if native:
                employee.hire_date = native
            elif not employee.hire_date:
                employee.hire_date = False

    def _get_company_experience_years(self, as_of=None):
        """Company experience in years as of `as_of` (default: today).

        Measured from `hire_date` at the requested date rather than "now":
        the seniority bonus must use the experience the employee had at the
        payslip date, otherwise a December recomputation of a January payslip
        would apply a different percentage.
        """
        self.ensure_one()
        if not self.hire_date:
            return 0.0
        ref_date = as_of or fields.Date.context_today(self)
        if ref_date < self.hire_date:
            return 0.0
        delta = relativedelta(ref_date, self.hire_date)
        return delta.years + delta.months / 12.0

    @api.depends('hire_date')
    def _compute_work_experience_company(self):
        """Display-only, deliberately not stored: the value depends on today's
        date, so a stored copy goes stale silently (it used to freeze at the
        moment hire_date was last written). Computations must call
        `_get_company_experience_years(as_of)` instead.
        """
        today = fields.Date.context_today(self)
        for employee in self:
            employee.work_experience_company = employee._get_company_experience_years(today)

    def _get_vacation_anchor_date(self):
        """Date the vacation work year is counted from.

        Defaults to hire_date, which itself derives from the contract
        versions. l10n_ua_hr_holidays overrides this to honour a work year
        carried over from another company (art. 9 §3 of the Vacation Law):
        there the new contract — and hence hire_date — starts on the transfer
        date, while the vacation seniority keeps running.
        """
        self.ensure_one()
        return self.hire_date

    def _get_work_year_for_date(self, ref_date):
        """Return (period_start, period_end, period_index) of the work year
        containing ref_date, anchored to `_get_vacation_anchor_date()`.

        Used by l10n_ua_hr_holidays to accrue annual vacations per the
        Ukrainian Vacation Law (work year = 12 months from the anchor).

        Returns (False, False, 0) when the anchor is missing or ref_date
        precedes it.
        """
        self.ensure_one()
        anchor = self._get_vacation_anchor_date()
        if not anchor or not ref_date or ref_date < anchor:
            return (False, False, 0)
        delta = relativedelta(ref_date, anchor)
        period_index = delta.years + 1
        period_start = anchor + relativedelta(years=period_index - 1)
        period_end = anchor + relativedelta(years=period_index) - relativedelta(days=1)
        return (period_start, period_end, period_index)

    def _get_p2_hire_date(self):
        """Hire date printed on the П-2 card: start of the CURRENT contract.

        Form П-2 (Держкомстат/Міноборони order No 495/656 of 25.12.2009)
        documents one employment contract: it closes with a single "Дата і
        причина звільнення" line signed by the employee, and a re-hire starts
        a NEW card while the old one is filed for 75 years (Мін'юст order
        No 578/5, art. 499).

        The card therefore takes hr.version.contract_date_start and not
        hire_date: the core aggregation behind hire_date merges two spells
        whenever the gap between them is shorter than four days, which would
        print the previous employment date on a card documenting a new
        contract.

        sudo() — contract dates live on hr.version behind
        hr.group_hr_manager, while the card is printed by HR officers.
        """
        self.ensure_one()
        version = self.sudo().current_version_id
        return version.contract_date_start if version else False

    DISABILITY_GROUP_ROMAN = {'1': 'I', '2': 'II', '3': 'III'}

    def _get_p2_additional_info(self):
        """Text for the "Додаткові відомості" line of the П-2 card.

        The form carries one free line there, so the disability data is
        rendered as a sentence instead of a table. Values the system does not
        hold — the certificate series and number — stay as blanks for a
        handwritten entry, the same way the printed form does it.
        """
        self.ensure_one()
        group = self.DISABILITY_GROUP_ROMAN.get(self.disability_group)
        if not group:
            return ''
        act_date = (self.disability_date_from.strftime('%d.%m.%Y')
                    if self.disability_date_from else '____________')
        # The reason follows the group in brackets, the way the card used to
        # show it in the dropped table.
        reason = ' (%s)' % self.disability_reason.strip() if self.disability_reason else ''
        text = (
            'Інвалідність %s групи%s, посвідчення серія ______ № ______, '
            'довідка до акта МСЕК (витяг рішення експертної комісії) '
            'від %s № %s'
            % (group, reason, act_date, self.disability_document or '______')
        )
        # An open-ended disability carries no expiry date, so the clause is
        # appended only when one is set.
        if self.disability_date_to:
            text += ', строком до %s' % self.disability_date_to.strftime('%d.%m.%Y')
        return text

    def _get_p2_dismissal_text(self):
        """Text filling the "Дата і причина звільнення (підстава)" line.

        Built from the confirmed dismissal order as
        "<date> <reason>, наказ № <number> від <order date>". Returns an empty
        string while no dismissal order is confirmed, so the form keeps its
        blank line for a handwritten entry.

        The order model lives in l10n_ua_hr_documents, which this module does
        not depend on — hence the presence check.
        """
        self.ensure_one()
        if 'hr.order' not in self.env:
            return ''
        order = self.env['hr.order'].sudo().search([
            ('employee_id', '=', self.id),
            ('order_type', '=', 'dismissal'),
            ('state', '=', 'confirmed'),
        ], order='date_dismissal desc, date desc, id desc', limit=1)
        if not order:
            return ''
        parts = []
        dismissal_date = order.date_dismissal or order.date
        if dismissal_date:
            parts.append(dismissal_date.strftime('%d.%m.%Y'))
        if order.dismissal_reason:
            # The reason is a Text field; the form line takes a single line.
            parts.append(' '.join(order.dismissal_reason.split()))
        reference = []
        if order.name and order.name != 'New':
            reference.append('наказ № %s' % order.name)
        if order.date:
            reference.append('від %s' % order.date.strftime('%d.%m.%Y'))
        text = ' '.join(parts)
        if reference:
            reference = ' '.join(reference)
            text = '%s, %s' % (text, reference) if text else reference
        return text

    @api.onchange('registration_same_as_actual', *REGISTRATION_ADDRESS_MAP)
    def _onchange_registration_same_as_actual(self):
        """Mirror the private address into the registration block in the UI."""
        if self.registration_same_as_actual:
            for private_field, registration_field in REGISTRATION_ADDRESS_MAP.items():
                self[registration_field] = self[private_field]

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._sync_registration_address_from_private()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if not REGISTRATION_SYNC_TRIGGERS.isdisjoint(vals):
            self._sync_registration_address_from_private()
        return res

    def _sync_registration_address_from_private(self):
        """Copy the private (actual) address onto the registration block.

        Only records with the flag set are touched. Employees needing the same
        values are written together, so a mass update (import, transfer) costs a
        handful of queries instead of one per employee. A plain write() is used
        rather than a super() jump so that overrides of other modules and the
        chatter tracking still run; it cannot recurse because none of the
        written fields is a sync trigger.

        The address is always read from the *current* version: a form opened on
        a past or future version puts that version in the context, and mirroring
        it would overwrite today's registration address with a historical one.
        """
        records = self.with_context(version_id=False)
        grouped = defaultdict(lambda: records.browse())
        for employee in records.filtered('registration_same_as_actual'):
            vals = employee._registration_address_vals()
            if vals:
                grouped[tuple(sorted(vals.items()))] += employee
        for vals, employees in grouped.items():
            employees.write(dict(vals))

    def _registration_address_vals(self):
        """Values that would bring this employee's registration block in line."""
        self.ensure_one()
        vals = {}
        for private_field, registration_field in REGISTRATION_ADDRESS_MAP.items():
            new_value = self._address_field_value(private_field)
            if self._address_field_value(registration_field) != new_value:
                vals[registration_field] = new_value
        return vals

    def _address_field_value(self, fname):
        """Comparable, writable value of an address field (id for many2one)."""
        value = self[fname]
        if self._fields[fname].type == 'many2one':
            return value.id
        return value or False

    def _get_ua_actual_address_display(self):
        """One-line actual (private) address, for printed forms and bank files."""
        self.ensure_one()
        return _join_address_parts([
            self.private_zip, self.private_state_id.name, self.private_city,
            self.private_street, self.private_street2])

    def _get_ua_registration_address_display(self):
        """One-line registration address, for printed forms and bank files.

        Falls back to the private address when the flag is set, so records that
        predate the sync (or were written straight to SQL) still print.
        """
        self.ensure_one()
        if self.registration_same_as_actual:
            return self._get_ua_actual_address_display()
        return _join_address_parts([
            self.registration_zip, self.registration_region_id.name,
            self.registration_city, self.registration_street,
            self.registration_street2])

    @api.constrains('rnokpp')
    def _check_rnokpp(self):
        validate_rnokpp = self.env['ir.config_parameter'].sudo().get_param(
            'hr_ua.validate_rnokpp', 'True')
        if validate_rnokpp.lower() == 'true':
            for employee in self:
                if employee.rnokpp and not self._validate_rnokpp(employee.rnokpp):
                    raise ValidationError('Invalid RNOKPP (IPN) checksum!')

    @staticmethod
    def _validate_rnokpp(rnokpp):
        """Validate Ukrainian RNOKPP (IPN) checksum."""
        if not rnokpp or len(rnokpp) != 10 or not rnokpp.isdigit():
            return False
        weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
        checksum = sum(int(rnokpp[i]) * weights[i] for i in range(9))
        control = (checksum % 11) % 10
        return control == int(rnokpp[9])

    @api.constrains('passport_id', 'document_type')
    def _check_passport_number(self):
        """Validate passport/ID number format based on document type."""
        for employee in self:
            if employee.passport_id:
                if employee.document_type == 'passport' and len(employee.passport_id) != 6:
                    raise ValidationError('Old passport number must be 6 digits!')
                if employee.document_type == 'id_card' and len(employee.passport_id) != 9:
                    raise ValidationError('ID card number must be 9 digits!')

    _rnokpp_uniq = models.Constraint(
	'unique(rnokpp, company_id)',
        'RNOKPP (IPN) must be unique!',
    )

    # === Staffing Table / Job filtering ===
    allowed_job_ids = fields.Many2many(
        'hr.job', 
        compute='_compute_allowed_job_ids',
        string='Allowed Jobs (by Staffing Table)'
    )

    @api.depends('department_id')
    def _compute_allowed_job_ids(self):
        for employee in self:
            if employee.department_id:
                # Find approved staffing records for the selected department
                staffing_records = self.env['hr.staffing.table'].search([
                    ('department_id', '=', employee.department_id.id),
                    ('state', '=', 'approved') 
                ])
                employee.allowed_job_ids = staffing_records.mapped('job_id')
            else:
                # If no department is selected, allow all jobs
                employee.allowed_job_ids = self.env['hr.job'].search([])

    @api.onchange('department_id')
    def _onchange_department_clear_job(self):
        """Clears the job position field if it does not belong to the newly selected department"""
        if self.job_id and self.job_id not in self.allowed_job_ids:
            self.job_id = False
