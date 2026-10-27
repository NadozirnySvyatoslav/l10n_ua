import base64
import calendar
import io
import logging
import re
from datetime import timedelta
from xml.sax.saxutils import escape as xml_escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

_logger = logging.getLogger(__name__)

# Покупець у ПН, що не надається покупцю (Порядок 1307 п. 16).
NON_PAYER_IPN = '100000000000'
NON_PAYER_NAME = 'Неплатник'
# Умовний ІПН покупця за типом причини: 02 — неплатник, 07 — нерезидент
# (вивезення товарів), у ПН на експорт покупцем лишається сам нерезидент.
CONDITIONAL_IPN = {'02': NON_PAYER_IPN, '07': '300000000000'}

# Податкова накладна J1201016 (Порядок 1307 у редакції наказу № 400 від
# 09.08.2024); структура — XSD пакета СКЗ 1.34.0.0 (tests/schemas).
PN_FORM = ('J12', '010', '16')
SOFTWARE = 'Odoo l10n_ua'
# Номер митної декларації в ПН на експорт (тип DGNUM_MD)
CUSTOMS_NUMBER_RE = r'[0-9]{2}UA[0-9]{3}[K0-9][0-9]{2}[A-Z0-9]{7}.'

VAT_RATE_SELECTION = [
    ('20', '20%'),
    ('14', '14%'),
    ('7', '7%'),
    ('0', '0%'),
    ('exempt', 'Звільнено'),
]


class L10nUaTaxInvoice(models.Model):
    _name = 'l10n_ua.tax.invoice'
    _description = 'Tax Invoice (Податкова накладна)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'date desc, number desc'

    name = fields.Char(
        string='Назва',
        compute='_compute_name',
        store=True,
    )
    doc_type = fields.Selection(
        selection=[
            ('pn', 'ПН (Податкова накладна)'),
            ('rk', 'РК (Розрахунок коригування)'),
        ],
        string='Тип документа',
        default='pn',
        required=True,
        tracking=True,
    )
    number = fields.Char(
        string='Номер',
        required=True,
        tracking=True,
    )
    date = fields.Date(
        string='Дата складання',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    vat_method = fields.Selection(
        selection=[
            ('first_event', 'Перша подія'),
            ('cash', 'Касовий метод'),
            ('document', 'Дата документа'),
        ],
        string='Правило визнання',
        default='first_event',
        tracking=True,
        help='За яким правилом визначено дату складання: загальне правило '
             'першої події (ст. 187 ПКУ), касовий метод (п. 187.10) або '
             'дата самого документа — для вхідної ПН, яку склав постачальник, '
             'і для РК, що складається на дату коригуючої події.',
    )
    invoice_type = fields.Selection(
        selection=[
            ('issued', 'Видана'),
            ('received', 'Отримана'),
        ],
        string='Тип',
        required=True,
        default='issued',
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Контрагент',
        required=True,
        tracking=True,
    )
    partner_ipn = fields.Char(
        related='partner_id.ipn',
        string='ІПН контрагента',
    )
    partner_name = fields.Char(
        related='partner_id.name',
        string='Назва контрагента',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Пов\'язаний рахунок',
    )
    # RK (correction) fields
    original_invoice_id = fields.Many2one(
        'l10n_ua.tax.invoice',
        string='Оригінальна ПН',
        help='Посилання на оригінальну ПН для розрахунку коригування',
    )
    reason = fields.Char(
        string='Причина коригування',
    )
    is_import = fields.Boolean(
        string='Імпортна операція',
        default=False,
    )
    # ПН, що не надається покупцю (Порядок 1307 п. 16): покупець —
    # «Неплатник» з ІПН 100000000000, у ПН — тип причини.
    non_payer_reason = fields.Selection(
        selection=[
            ('02', '02 — постачання неплатнику податку'),
            ('07', '07 — вивезення товарів за межі митної території'),
        ],
        string='Не підлягає наданню покупцю',
        tracking=True,
        help='Тип причини, з якої ПН не видається покупцю. Покупцем у документі '
             'зазначається «Неплатник», ІПН — 100000000000.',
    )
    # Ознака п. 198.5 / 199.1 ПКУ: зобов'язання йдуть у рядки 4.x декларації,
    # у Д1 (табл. 1.1/1.2) — графа 5 «+».
    vat_special_basis = fields.Selection(
        selection=[
            ('198_5', 'п. 198.5 — використання поза оподатковуваними операціями'),
            ('199_1', 'п. 199.1 — частка використання в неоподатковуваних операціях'),
        ],
        string='Нарахування за п. 198.5 / 199.1',
        tracking=True,
        help='ПН, складена на себе на зобов\'язання за п. 198.5 або 199.1 ПКУ. РК до такої '
             'ПН (без власної ознаки) успадковує її з оригіналу.',
    )
    vat_199_recalc = fields.Boolean(
        string='Річний перерахунок частки (п. 199.4)',
        tracking=True,
        help='РК за підсумками року до ПН за п. 199.1: Д1 таблиця 1.2.4 і Д5 таблиця 2',
    )
    # З 01.07.2024 обов'язкові в ПН на експорт: реквізити контракту й МД.
    contract_number = fields.Char(string='Номер договору (контракту)')
    contract_date = fields.Date(string='Дата договору (контракту)')
    customs_number = fields.Char(
        string='Номер митної декларації',
        help='У форматі ЄАІС, напр. 26UA500020000123U4 — для ПН на експорт (тип причини 07).')
    customs_date = fields.Date(string='Дата митної декларації')
    signer_name = fields.Char(
        string='Склав', compute='_compute_signer', store=True, readonly=False,
        help='Ініціали та прізвище особи, яка склала ПН.')
    signer_rnokpp = fields.Char(
        string='РНОКПП особи, що склала', compute='_compute_signer', store=True, readonly=False)
    # Lines
    line_ids = fields.One2many(
        'l10n_ua.tax.invoice.line',
        'tax_invoice_id',
        string='Рядки',
    )
    # Totals
    total_base = fields.Monetary(
        string='База оподаткування',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_vat = fields.Monetary(
        string='Сума ПДВ',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_amount = fields.Monetary(
        string='Загальна сума',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    # State
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('registered', 'Зареєстровано в ЄРПН'),
            ('cancelled', 'Скасовано'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )
    # ERPN
    erpn_number = fields.Char(
        string='Номер реєстрації ЄРПН',
        tracking=True,
    )
    erpn_date = fields.Datetime(
        string='Дата реєстрації ЄРПН',
    )
    registration_deadline = fields.Date(
        string='Граничний строк реєстрації',
        compute='_compute_registration_deadline',
        store=True,
        help='Граничний строк реєстрації в ЄРПН (воєнний час)',
    )
    # Received PN tracking
    received_status = fields.Selection(
        selection=[
            ('expected', 'Очікується'),
            ('received', 'Отримано'),
            ('erpn_verified', 'Перевірено в ЄРПН'),
            ('included', 'Включено в декларацію'),
        ],
        string='Статус отримання',
        default='expected',
        tracking=True,
    )
    received_date = fields.Date(
        string='Дата отримання',
        tracking=True,
    )
    erpn_verified_date = fields.Date(
        string='Дата перевірки ЄРПН',
        tracking=True,
    )
    erpn_receipt = fields.Text(
        string='Квитанція ЄРПН',
        readonly=True,
        copy=False,
        help='Відповідь/квитанція кабінету ДПС про реєстрацію податкової накладної.',
    )
    is_overdue = fields.Boolean(
        string='Прострочено',
        compute='_compute_is_overdue',
        store=True,
    )

    # XML
    file_xml = fields.Binary(
        string='XML файл',
        attachment=True,
    )
    file_xml_name = fields.Char(
        string='Ім\'я XML файлу',
    )

    @api.onchange('invoice_type', 'doc_type')
    def _onchange_vat_method(self):
        """Вхідна ПН і РК датуються самим документом, а не нашим правилом.

        З рахунка це проставляє `action_create_tax_invoice`; при ручному
        заведенні поле інакше лишалося б дефолтним 'first_event' — тобто
        стверджувало б про документ те саме, що міграція виправляє для
        історичних записів.
        """
        for rec in self:
            if rec.invoice_type == 'received' or rec.doc_type == 'rk':
                rec.vat_method = 'document'
            elif rec.vat_method == 'document':
                rec.vat_method = 'first_event'

    @api.depends('doc_type', 'number', 'date')
    def _compute_name(self):
        for rec in self:
            prefix = 'ПН' if rec.doc_type == 'pn' else 'РК'
            if rec.number and rec.date:
                rec.name = f'{prefix} {rec.number} від {rec.date}'
            else:
                rec.name = _('Нова')

    @api.depends('line_ids.base_amount', 'line_ids.vat_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_base = sum(rec.line_ids.mapped('base_amount'))
            rec.total_vat = sum(rec.line_ids.mapped('vat_amount'))
            rec.total_amount = rec.total_base + rec.total_vat

    @api.depends('date', 'company_id.l10n_ua_erpn_deadline_mode')
    def _compute_registration_deadline(self):
        """ERPN registration deadlines depending on company mode.

        Wartime (default):
        - 1st-15th of month → 5th of next month
        - 16th-end of month → 18th of next month

        Peacetime:
        - 1st-15th of month → last day of same month
        - 16th-end of month → 15th of next month
        """
        for rec in self:
            if not rec.date:
                rec.registration_deadline = False
                continue
            d = rec.date
            mode = rec.company_id.l10n_ua_erpn_deadline_mode or 'wartime'
            next_month_first = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            if mode == 'wartime':
                if d.day <= 15:
                    rec.registration_deadline = next_month_first.replace(day=5)
                else:
                    rec.registration_deadline = next_month_first.replace(day=18)
            else:  # peacetime
                if d.day <= 15:
                    last_day = calendar.monthrange(d.year, d.month)[1]
                    rec.registration_deadline = d.replace(day=last_day)
                else:
                    rec.registration_deadline = next_month_first.replace(day=15)

    @api.depends('registration_deadline', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = (
                rec.state == 'draft'
                and rec.registration_deadline
                and rec.registration_deadline < today
            )

    def action_mark_received(self):
        """Mark received PN as received with today's date."""
        self.write({
            'received_status': 'received',
            'received_date': fields.Date.context_today(self),
        })

    def action_mark_erpn_verified(self):
        """Mark received PN as verified in ERPN."""
        self.write({
            'received_status': 'erpn_verified',
            'erpn_verified_date': fields.Date.context_today(self),
        })

    def action_register_erpn(self):
        """Відкрити клієнтське КЕП-підписування для реєстрації в ЄРПН (#146).

        Тонка обгортка над спільним action_kep_submit (l10n_ua.dps.submit.mixin):
        валідує чернетку/XML/конфіг і відкриває універсальний діалог підпису.
        Статус 'registered' — лише після квитанції ДПС.
        """
        return self.action_kep_submit()

    # --- перевизначення контракту l10n_ua.dps.submit.mixin ---

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Можна реєструвати тільки чернетки.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.file_xml:
            self.action_generate_xml()

    def _dps_document_b64(self):
        self._dps_ensure_xml()
        xml = self.file_xml or b''
        return xml.decode() if isinstance(xml, bytes) else xml

    def _dps_filename(self):
        return self.file_xml_name or self._generate_xml_filename()

    def _dps_submit_label(self):
        return _('Зареєструвати в ЄРПН')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'registered',
            'erpn_date': fields.Datetime.now(),
            'erpn_receipt': receipt,
        })
        self.message_post(
            body=_('Зареєстровано в ЄРПН. Квитанція: %s') % (receipt or '—'))

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})

    @api.depends('company_id')
    def _compute_signer(self):
        for rec in self:
            if not rec.signer_name:
                rec.signer_name = rec.company_id.l10n_ua_vat_signer_name
                rec.signer_rnokpp = rec.company_id.l10n_ua_vat_signer_rnokpp

    def action_generate_xml(self):
        """Generate XML for tax invoice per Наказ Мінфіну №1307."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('XML можна генерувати тільки для чернеток.'))

        # Гр. 3.1 (УКТ ЗЕД) для товару і гр. 3.3 (ДКПП) для послуги —
        # обов'язкові за Порядком 1307 п. 16: ЄРПН не реєструє рядок без коду.
        # Доки код підтягувався з поля, якого не існувало, документ виходив
        # порожнім і помилка спливала аж у квитанції ДПС. Хай уже тут.
        uncoded = self.line_ids.filtered(
            lambda line: not line.uktzed_code and not line.dkpp_code)
        if uncoded:
            raise UserError(_(
                'Рядки без коду УКТ ЗЕД або ДКПП — ЄРПН таку ПН не '
                'зареєструє:\n%(lines)s\n\nКод береться з номенклатури; '
                'заповніть його на товарі й перестворіть ПН або впишіть у '
                'рядок вручну.',
                lines='\n'.join('— %s' % (line.name or '?') for line in uncoded),
            ))

        if self.doc_type == 'pn':
            xml_bytes = self._render_j1201016()
            filename = dps_standard_filename(xml_bytes) or self._generate_xml_filename()
        else:
            # РК — ще у спрощеному форматі (J1201216 — окремий крок)
            xml_bytes = self._build_xml().encode('windows-1251')
            filename = self._generate_xml_filename()
        self.write({
            'file_xml': base64.b64encode(xml_bytes),
            'file_xml_name': filename,
        })

    def _generate_xml_filename(self):
        """Generate filename per Order №729 pattern."""
        self.ensure_one()
        company = self.company_id
        edrpou = company.company_registry or company.vat or '000000000'
        # J for legal entity, F for FOP
        entity = 'J' if company.company_registry else 'F'
        date_str = (self.date or fields.Date.today()).strftime('%Y%m%d%H%M%S')
        return f'{entity}1201011_{edrpou}_{date_str}_1.xml'

    # ----------------------------------------------------- J1201016

    def _pn_rate_code(self, line):
        """Код ставки графи 8: 20 / 7 / 14, 901 — 0 % експорт, 902 — 0 % на
        митній території, 903 — звільнено."""
        if line.vat_rate == '0':
            export = self.non_payer_reason == '07' or (
                self.partner_id.country_id and self.partner_id.country_id.code != 'UA')
            return '901' if export else '902'
        return {'exempt': '903'}.get(line.vat_rate, line.vat_rate)

    def _pn_signer(self):
        """(ім'я, РНОКПП) особи, що склала ПН: з ПН, інакше з налаштувань компанії —
        ПН, створені до заповнення налаштувань, теж мають формуватися."""
        company = self.company_id
        if self.signer_name and self.signer_rnokpp:
            return self.signer_name, self.signer_rnokpp
        return company.l10n_ua_vat_signer_name, company.l10n_ua_vat_signer_rnokpp

    def _pn_office_code(self):
        # довідник ДПІ доступний лише групам UA — бухгалтеру без них теж треба XML
        company = self.company_id.sudo()
        office = company.l10n_ua_tax_office_id
        return re.sub(r'\D', '', (office.code if office else '') or company.tax_office_code or '')

    def _pn_number(self):
        digits = re.findall(r'\d+', self.number or '')
        return int(digits[-1]) if digits else 0

    def _pn_buyer(self):
        """(назва, ІПН, ЄДРПОУ) покупця для ПН."""
        partner = self.partner_id.commercial_partner_id
        if self.non_payer_reason:
            name = NON_PAYER_NAME if self.non_payer_reason == '02' else partner.name
            return name, CONDITIONAL_IPN.get(self.non_payer_reason, NON_PAYER_IPN), ''
        ipn = re.sub(r'\D', '', partner.vat or partner.ipn or '')
        return partner.name, ipn, re.sub(r'\D', '', partner.edrpou or '')

    def _check_j1201016_ready(self):
        self.ensure_one()
        company = self.company_id
        problems = []
        if not re.fullmatch(r'\d{12}', company.l10n_ua_vat_ipn or ''):
            problems.append(_('ІПН платника ПДВ компанії (12 цифр)'))
        if not re.fullmatch(r'\d{4}', self._pn_office_code()):
            problems.append(_('контролюючий орган компанії (код ДПІ)'))
        if not re.fullmatch(r'\d{8,10}', re.sub(r'\D', '', company.edrpou or company.company_registry or '')):
            problems.append(_('код ЄДРПОУ компанії'))
        if not self._pn_number():
            problems.append(_('номер ПН'))
        signer_name, signer_rnokpp = self._pn_signer()
        if not signer_name or not re.fullmatch(r'\d{10}', signer_rnokpp or ''):
            problems.append(_('особа, що складає ПН, і її РНОКПП (налаштування ПДВ компанії)'))
        _name, ipn, _tin = self._pn_buyer()
        if not re.fullmatch(r'\d{12}', ipn):
            problems.append(_('ІПН покупця-платника ПДВ (12 цифр) — або позначте ПН як таку, що не '
                              'надається покупцю'))
        if self.non_payer_reason == '07':
            if not (self.contract_number and self.contract_date):
                problems.append(_('номер і дата контракту (обов\'язкові в ПН на експорт)'))
            if not (self.customs_date and re.fullmatch(CUSTOMS_NUMBER_RE, self.customs_number or '')):
                problems.append(_('дата й номер митної декларації у форматі ЄАІС, напр. 26UA500020000123U4'))
        if problems:
            raise UserError(_('Неможливо сформувати XML податкової накладної:\n• %s') % '\n• '.join(problems))

    def _render_j1201016(self):
        """XML податкової накладної J1201016 за XSD ДПС, windows-1251."""
        self.ensure_one()
        self._check_j1201016_ready()
        company = self.company_id
        office = self._pn_office_code()
        tin = re.sub(r'\D', '', company.edrpou or company.company_registry or '')
        number = self._pn_number()
        esc = lambda v: xml_escape(str(v or ''))
        dec = lambda v, d=2: ('%.' + str(d) + 'f') % (v or 0.0)

        def plain(v):
            # Decimal…_R: до 12 / 6 знаків, без хвостових нулів
            text = ('%.12f' % v).rstrip('0').rstrip('.')
            return text or '0'

        head = (
            '<DECLARHEAD>'
            f'<TIN>{tin}</TIN><C_DOC>{PN_FORM[0]}</C_DOC><C_DOC_SUB>{PN_FORM[1]}</C_DOC_SUB>'
            f'<C_DOC_VER>{PN_FORM[2]}</C_DOC_VER><C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>{number}</C_DOC_CNT>'
            f'<C_REG>{office[:2]}</C_REG><C_RAJ>{office[2:4]}</C_RAJ>'
            f'<PERIOD_MONTH>{self.date.month}</PERIOD_MONTH><PERIOD_TYPE>1</PERIOD_TYPE>'
            f'<PERIOD_YEAR>{self.date.year}</PERIOD_YEAR><C_STI_ORIG>{office}</C_STI_ORIG>'
            '<C_DOC_STAN>1</C_DOC_STAN><LINKED_DOCS xsi:nil="true"/>'
            f'<D_FILL>{fields.Date.context_today(self):%d%m%Y}</D_FILL><SOFTWARE>{SOFTWARE}</SOFTWARE>'
            '</DECLARHEAD>')

        body = []
        if self.non_payer_reason:
            body.append(f'<HORIG1>1</HORIG1><HTYPR>{self.non_payer_reason}</HTYPR>')
        if self.contract_number and self.contract_date:
            body.append(f'<R001G1D>{self.contract_date:%d%m%Y}</R001G1D>'
                        f'<R001G2S>{esc(self.contract_number)}</R001G2S>')
        if self.customs_number and self.customs_date:
            body.append(f'<R002G1D>{self.customs_date:%d%m%Y}</R002G1D>'
                        f'<R002G2S>{esc(self.customs_number)}</R002G2S>')
        buyer_name, buyer_ipn, buyer_tin = self._pn_buyer()
        body.append(f'<HFILL>{self.date:%d%m%Y}</HFILL><HNUM>{number}</HNUM>')
        body.append(f'<HNAMESEL>{esc(company._l10n_ua_dps_name())}</HNAMESEL>'
                    f'<HNAMEBUY>{esc(buyer_name)}</HNAMEBUY>'
                    f'<HKSEL>{company.l10n_ua_vat_ipn}</HKSEL>'
                    f'<HTINSEL>{tin}</HTINSEL><HKS>1</HKS>'
                    f'<HKBUY>{buyer_ipn}</HKBUY>')
        if buyer_tin and re.fullmatch(r'\d{5,10}', buyer_tin):
            body.append(f'<HTINBUY>{buyer_tin}</HTINBUY><HKB>1</HKB>')

        # підсумки за кодами ставок
        base = {}
        vat = {}
        for line in self.line_ids:
            code = self._pn_rate_code(line)
            base[code] = base.get(code, 0.0) + line.base_amount
            vat[code] = vat.get(code, 0.0) + line.vat_amount
        vat_total = sum(vat.get(c, 0.0) for c in ('20', '7', '14'))
        body.append(f'<R04G11>{dec(sum(base.values()) + vat_total)}</R04G11>')
        body.append(f'<R03G11>{dec(vat_total)}</R03G11>')
        for tag, code in (('R03G7', '20'), ('R03G109', '7'), ('R03G14', '14')):
            if code in vat:
                body.append(f'<{tag}>{dec(vat[code])}</{tag}>')
        for tag, code in (('R01G7', '20'), ('R01G109', '7'), ('R01G14', '14'), ('R01G9', '901'),
                          ('R01G8', '902'), ('R01G10', '903')):
            if code in base:
                body.append(f'<{tag}>{dec(base[code])}</{tag}>')

        # таблиця — стовпцями, як вимагає послідовність XSD
        lines = list(self.line_ids)
        columns = [
            ('G3S', lambda l: esc(l.name)),
            ('G4', lambda l: l.uktzed_code),
            ('G32', lambda l: '1' if l.is_import else None),
            ('G33', lambda l: l.dkpp_code),
            ('G4S', lambda l: esc(l.uom_id.name) if l.uom_id else None),
            ('G105_2S', lambda l: l.uom_id.l10n_ua_kspovo_code if l.uom_id else None),
            ('G5', lambda l: plain(l.quantity)),
            ('G6', lambda l: plain(l.price_unit)),
            ('G008', lambda l: self._pn_rate_code(l)),
            ('G009', lambda l: l.benefit_code),
            ('G010', lambda l: dec(l.base_amount)),
            ('G11_10', lambda l: plain(l.vat_amount)),
        ]
        for col, get in columns:
            for num, line in enumerate(lines, 1):
                value = get(line)
                if value in (None, False, ''):
                    continue
                body.append(f'<RXXXX{col} ROWNUM="{num}">{value}</RXXXX{col}>')
        signer_name, signer_rnokpp = self._pn_signer()
        body.append(f'<HBOS>{esc(signer_name)}</HBOS><HKBOS>{signer_rnokpp}</HKBOS>')

        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               f'xsi:noNamespaceSchemaLocation="{"".join(PN_FORM)}.xsd">'
               f'{head}<DECLARBODY>{"".join(body)}</DECLARBODY></DECLAR>')
        return xml.encode('windows-1251', errors='xmlcharrefreplace')

    def _build_xml(self):
        """Build basic XML structure for tax invoice."""
        self.ensure_one()
        company = self.company_id
        seller_ipn = company.l10n_ua_vat_ipn or company.vat or company.company_registry or ''
        buyer_ipn = self.partner_ipn or ''
        buyer_name = self.partner_id.name
        if self.non_payer_reason:
            buyer_ipn, buyer_name = NON_PAYER_IPN, NON_PAYER_NAME

        lines_xml = []
        for i, line in enumerate(self.line_ids, 1):
            rate_code = {
                '20': '20',
                '14': '14',
                '7': '7',
                '0': '0',
                'exempt': '903',  # code for exempt
            }.get(line.vat_rate, '20')
            lines_xml.append(
                f'    <RYADOK ROWNUM="{i}">'
                f'<OBSAG>{line.name or ""}</OBSAG>'
                f'<KODU>{line.uktzed_code or ""}</KODU>'
                f'<KODP>{line.dkpp_code or ""}</KODP>'
                f'<ODINICI>{line.uom_id.name if line.uom_id else "шт."}</ODINICI>'
                f'<KILK>{line.quantity:.6f}</KILK>'
                f'<CINA>{line.price_unit:.6f}</CINA>'
                f'<KOD_STAVKI>{rate_code}</KOD_STAVKI>'
                f'<KOD_PILGI>{line.benefit_code or ""}</KOD_PILGI>'
                f'<OBSAG_BEZ_PDV>{line.base_amount:.2f}</OBSAG_BEZ_PDV>'
                f'<SUMA_PDV>{line.vat_amount:.2f}</SUMA_PDV>'
                f'</RYADOK>'
            )
        lines_str = '\n'.join(lines_xml)

        xml = f"""<?xml version="1.0" encoding="windows-1251"?>
<DECLAR>
  <DECLARBODY>
    <HNUM>{self.number}</HNUM>
    <HDATE>{self.date.strftime('%d%m%Y')}</HDATE>
    <HTYPE>{'00' if self.doc_type == 'pn' else '01'}</HTYPE>
    <SELLER_IPN>{seller_ipn}</SELLER_IPN>
    <SELLER_NAME>{company.name}</SELLER_NAME>
    <BUYER_IPN>{buyer_ipn}</BUYER_IPN>
    <BUYER_NAME>{buyer_name}</BUYER_NAME>{f'''
    <HTYPR>{self.non_payer_reason}</HTYPR>''' if self.non_payer_reason else ''}
    <IS_IMPORT>{'1' if self.is_import else '0'}</IS_IMPORT>
    <RYADKI>
{lines_str}
    </RYADKI>
    <ZAGALNA_SUMA_BEZ_PDV>{self.total_base:.2f}</ZAGALNA_SUMA_BEZ_PDV>
    <ZAGALNA_SUMA_PDV>{self.total_vat:.2f}</ZAGALNA_SUMA_PDV>
    <ZAGALNA_SUMA>{self.total_amount:.2f}</ZAGALNA_SUMA>
  </DECLARBODY>
</DECLAR>"""
        return xml


class L10nUaTaxInvoiceLine(models.Model):
    _name = 'l10n_ua.tax.invoice.line'
    _description = 'Tax Invoice Line'
    _order = 'sequence, id'

    tax_invoice_id = fields.Many2one(
        'l10n_ua.tax.invoice',
        string='Податкова накладна',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='Послідовність',
        default=10,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Товар/Послуга',
    )
    name = fields.Char(
        string='Опис (номенклатура)',
        required=True,
    )
    uktzed_code = fields.Char(
        string='Код УКТ ЗЕД',
        help='Код товару згідно з УКТ ЗЕД (для товарів)',
    )
    dkpp_code = fields.Char(
        string='Код ДКПП',
        help='Код послуги згідно з ДКПП (для послуг)',
    )
    is_import = fields.Boolean(
        string='Імпорт',
        default=False,
    )
    is_own_agro = fields.Boolean(
        string='Власна с/г продукція',
        default=False,
    )
    benefit_code = fields.Char(
        string='Код пільги',
    )
    quantity = fields.Float(
        string='Кількість',
        default=1.0,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Одиниця виміру',
    )
    price_unit = fields.Float(
        string='Ціна без ПДВ',
        digits=(16, 6),
        help='Ціна постачання одиниці без ПДВ (гр. 7 ПН). Не Monetary: '
             'округлення до копійки розсинхронізує базу з документом — '
             '379.99 на 3 одиниці дало б 126.66 × 3 = 379.98. Графа 7 '
             'допускає потрібну кількість знаків після коми.',
    )
    base_amount = fields.Monetary(
        string='База оподаткування',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    vat_rate = fields.Selection(
        selection=VAT_RATE_SELECTION,
        string='Ставка ПДВ',
        default='20',
    )
    vat_amount = fields.Monetary(
        string='Сума ПДВ',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    price_unit_display = fields.Char(
        string='Ціна без ПДВ (для друку)',
        compute='_compute_price_unit_display',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='tax_invoice_id.currency_id',
    )

    @api.depends('price_unit')
    def _compute_price_unit_display(self):
        """Копійки друкуємо завжди, зайві нулі — ні.

        Округлити гр. 7 до копійки не можна: тоді кількість × ціна перестане
        дорівнювати базі й друкована ПН суперечитиме сама собі.
        """
        for line in self:
            text = f'{line.price_unit:.6f}'.rstrip('0')
            decimals = len(text.partition('.')[2])
            line.price_unit_display = text + '0' * max(0, 2 - decimals)

    @api.depends('quantity', 'price_unit', 'vat_rate')
    def _compute_amounts(self):
        rates = {'20': 0.20, '14': 0.14, '7': 0.07, '0': 0.0}
        for line in self:
            currency = line.currency_id
            base = line.quantity * line.price_unit
            line.base_amount = currency.round(base) if currency else base
            vat = line.base_amount * rates.get(line.vat_rate, 0.0)
            line.vat_amount = currency.round(vat) if currency else vat
