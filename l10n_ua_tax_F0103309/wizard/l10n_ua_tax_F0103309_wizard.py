import logging
import re
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# DECLARBODY reporting-period marker tag, keyed by DECLARHEAD PERIOD_TYPE
# (1=month, 2=quarter, 3=half-year, 4=9-months, 5=year).
# Звірено з ОФІЦІЙНИМ XSD ДПС F0103309.xsd (DBody дозволяє саме ці елементи:
# H1KV, HHY, H3KV, HY) — пакет СКЗ 1.34.0.0. Тест: tests/test_xsd_validation.py.
F0103309_BODY_PERIOD_MARKER = {
    '1': 'H1KV',  # місяць (нетипово для гр.3) → I квартал
    '2': 'H1KV',  # I квартал
    '3': 'HHY',   # півріччя
    '4': 'H3KV',  # три квартали
    '5': 'HY',    # рік
}

# Identifies the generating software in DECLARHEAD/SOFTWARE (XSD-required element).
F0103309_SOFTWARE = 'Odoo l10n_ua'


class L10nUaTaxDocumentWizardF0103309(models.TransientModel):
    """
    Extension of base tax document wizard for F0103309 (Single Tax Declaration).

    This is the "Декларація платника єдиного податку" form version 9.

    XML field mapping (actual Tax Cabinet format):
    - R006G3: Total income for period
    - R008G3: Taxable income (same as R006G3 for Group 3)
    - R011G3: Single tax amount (income * tax_rate)
    - R012G3: Tax payable (same as R011G3)
    - R013G3: Tax already paid (from previous quarters)
    - R0141G3: Tax to pay this period (R011G3 - R013G3)
    - R014G3: Total tax to pay (same as R0141G3)
    - R023G3: Military tax (income * military_rate)
    - R024G3: Military tax already paid
    - R025G3: Military tax to pay (R023G3 - R024G3)
    """
    _inherit = 'l10n_ua.tax.document.wizard'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Get company from context or default
        company_id = res.get('company_id') or self.env.company.id
        company = self.env['res.company'].browse(company_id)

        if company:
            # Tax office
            if company.l10n_ua_tax_office_id:
                res['tax_office_id'] = company.l10n_ua_tax_office_id.id

            # FOP settings
            if company.l10n_ua_fop_group:
                res['fop_group'] = company.l10n_ua_fop_group
            if company.l10n_ua_tax_rate:
                res['tax_rate'] = company.l10n_ua_tax_rate

            # Activity codes (KVED) - fill from company settings
            if company.l10n_ua_kved_ids and 'activity_ids' in fields_list:
                activity_vals = []
                for company_kved in company.l10n_ua_kved_ids:
                    activity_vals.append((0, 0, {
                        'kved_id': company_kved.kved_id.id,
                        'is_primary': company_kved.is_primary,
                    }))
                if activity_vals:
                    res['activity_ids'] = activity_vals

        return res

    # F0103309 specific fields
    fop_group = fields.Selection(
        selection=[
            ('1', 'Group 1'),
            ('2', 'Group 2'),
            ('3', 'Group 3'),
        ],
        string='FOP Group',
        default='3',
    )
    tax_rate = fields.Float(
        string='Single Tax Rate (%)',
        default=5.0,
        help='Single tax rate: 5% for Group 3 (standard), 2% for e-residents, etc.',
    )
    military_rate = fields.Float(
        string='Military Tax Rate (%)',
        default=1.0,
        help='Military tax rate (збір): 1% of income',
    )
    declaration_type = fields.Selection(
        selection=[
            ('0', 'Reporting'),
            ('1', 'New Reporting'),
            ('2', 'Clarifying'),
        ],
        string='Declaration Type',
        default='0',
    )

    # Tax authority info
    tax_office_id = fields.Many2one(
        'l10n_ua.tax.office',
        string='Tax Office',
        domain=[('office_type', '=', 'district')],
    )

    # Income fields - cumulative for period
    income_total = fields.Float(
        string='Total Income (R006G3)',
        digits=(16, 2),
        help='Total income for the reporting period',
    )

    # Single tax fields
    tax_amount = fields.Float(
        string='Single Tax (R011G3)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Single tax amount = income × tax_rate',
    )
    tax_paid_prev = fields.Float(
        string='Tax Paid Previously (R013G3)',
        digits=(16, 2),
        help='Tax already paid in previous quarters of this year',
    )
    tax_to_pay = fields.Float(
        string='Tax to Pay (R0141G3)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Tax to pay = tax_amount - tax_paid_prev',
    )

    # Military tax fields
    military_amount = fields.Float(
        string='Military Tax (R023G3)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Military tax = income × military_rate',
    )
    military_paid_prev = fields.Float(
        string='Military Paid Previously (R024G3)',
        digits=(16, 2),
        help='Military tax already paid in previous quarters',
    )
    military_to_pay = fields.Float(
        string='Military to Pay (R025G3)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Military to pay = military_amount - military_paid_prev',
    )

    # Activity codes (KVED)
    activity_ids = fields.One2many(
        'l10n_ua.tax.document.wizard.activity',
        'wizard_id',
        string='Activity Codes',
    )

    # Employment info
    has_employees = fields.Boolean(string='Has Employees', default=False)
    employee_count = fields.Integer(string='Employee Count', default=0)

    # Bank journals for auto-fill
    journal_ids = fields.Many2many(
        'account.journal',
        string='Bank Journals',
        domain=[('type', '=', 'bank')],
        help='Select bank journals to compute income from transactions',
    )

    @api.depends('income_total', 'tax_rate', 'military_rate', 'tax_paid_prev', 'military_paid_prev')
    def _compute_tax_amounts(self):
        for rec in self:
            # Single tax calculation
            rec.tax_amount = rec.income_total * rec.tax_rate / 100
            rec.tax_to_pay = rec.tax_amount - rec.tax_paid_prev

            # Military tax calculation
            rec.military_amount = rec.income_total * rec.military_rate / 100
            rec.military_to_pay = rec.military_amount - rec.military_paid_prev

    def action_fill_from_bank(self):
        """Fill income from bank transactions."""
        self.ensure_one()

        if not self.journal_ids:
            raise UserError(_("Please select at least one bank journal first."))

        if not self.year:
            raise UserError(_("Please select a year first."))

        period = self.period
        year = self.year

        # Calculate date range based on period
        date_from = date(year, 1, 1)

        # Determine end date based on period
        if period in ('03', 'q1'):
            date_to = date(year, 3, 31)
        elif period in ('06', 'q2', 'h1'):
            date_to = date(year, 6, 30)
        elif period in ('09', 'q3'):
            date_to = date(year, 9, 30)
        elif period in ('12', 'q4', 'year'):
            date_to = date(year, 12, 31)
        else:
            # For monthly periods, calculate end of month
            try:
                month = int(period)
                if month == 12:
                    date_to = date(year, 12, 31)
                elif month == 2:
                    # Handle leap year
                    date_to = date(year, 2, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28)
                elif month in (4, 6, 9, 11):
                    date_to = date(year, month, 30)
                else:
                    date_to = date(year, month, 31)
            except (ValueError, TypeError):
                date_to = date(year, 12, 31)

        # Check if l10n_ua_bank_sync module is installed
        BankTransaction = self.env.get('l10n_ua.bank.transaction')
        if BankTransaction is None:
            raise UserError(_(
                "Bank sync module (l10n_ua_bank_sync) is not installed. "
                "Please install it to use auto-fill from bank transactions."
            ))

        # Get bank transactions for the period from ALL selected journals
        transactions = BankTransaction.search([
            ('journal_id', 'in', self.journal_ids.ids),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('amount', '>', 0),  # Only incoming (positive) amounts
        ])

        if not transactions:
            journal_names = ', '.join(self.journal_ids.mapped('name'))
            raise UserError(_(
                "No incoming transactions found for journals '%s' "
                "in period %s/%s (from %s to %s)."
            ) % (journal_names, period, year, date_from, date_to))

        # Calculate total income from all journals
        total_income = sum(tx.amount for tx in transactions)

        # Update income field using write() to persist to database
        self.write({'income_total': total_income})

        # Reopen the wizard to show updated values
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_fill_prev_payments(self):
        """Fill previously paid taxes from earlier declarations of this year."""
        self.ensure_one()

        if not self.year:
            raise UserError(_("Please select a year first."))

        # Determine previous period based on current period
        period = self.period
        prev_periods = []

        if period in ('06', 'q2', 'h1'):
            prev_periods = ['03', 'q1']
        elif period in ('09', 'q3'):
            prev_periods = ['03', 'q1', '06', 'q2', 'h1']
        elif period in ('12', 'q4', 'year'):
            prev_periods = ['03', 'q1', '06', 'q2', 'h1', '09', 'q3']

        if not prev_periods:
            raise UserError(_("No previous period for Q1 declaration."))

        # Search for previous declarations
        Document = self.env['l10n_ua.tax.document']
        prev_docs = Document.search([
            ('year', '=', self.year),
            ('period', 'in', prev_periods),
            ('document_type_id.code', '=', 'F0103309'),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'accepted'),
        ], order='period desc', limit=1)

        if not prev_docs:
            raise UserError(_("No accepted previous declaration found for this year."))

        if not prev_docs.file_xml:
            raise UserError(_("Previous declaration has no XML file."))

        # Parse XML to extract tax amounts
        try:
            xml_content = prev_docs.file_xml.content.decode('windows-1251', errors='replace')

            # Extract R011G3 (single tax amount)
            tax_match = re.search(r'<R011G3>([0-9.]+)</R011G3>', xml_content)
            tax_paid = float(tax_match.group(1)) if tax_match else 0.0

            # Extract R023G3 (military tax amount)
            military_match = re.search(r'<R023G3>([0-9.]+)</R023G3>', xml_content)
            military_paid = float(military_match.group(1)) if military_match else 0.0

            # Update fields
            self.write({
                'tax_paid_prev': tax_paid,
                'military_paid_prev': military_paid,
            })

            # Reopen wizard to show updated values
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        except Exception as e:
            raise UserError(_("Error parsing previous declaration XML: %s") % str(e))

    def _generate_xml_F0103309(self):
        """Generate XML for Single Tax Declaration (F0103309)."""
        self.ensure_one()

        # Determine reporting period
        period_type = self._get_period_type()
        period_month = self._get_period_month()

        # Build filename
        filename = f"{self.taxpayer_tin}_{self.year}_{period_month}_F0103309.xml"

        # Generate XML content
        xml = self._build_F0103309_xml(period_type, period_month)

        return xml, filename

    def _get_quarter_marker(self):
        """Get quarter marker tag (H1KV, H2KV, H3KV, H4KV) based on period."""
        period = self.period
        if period in ('03', 'q1'):
            return 'H1KV'
        elif period in ('06', 'q2', 'h1'):
            return 'H2KV'
        elif period in ('09', 'q3'):
            return 'H3KV'
        elif period in ('12', 'q4', 'year'):
            return 'H4KV'
        else:
            # For monthly, determine quarter
            try:
                month = int(period)
                if month <= 3:
                    return 'H1KV'
                elif month <= 6:
                    return 'H2KV'
                elif month <= 9:
                    return 'H3KV'
                else:
                    return 'H4KV'
            except (ValueError, TypeError):
                return 'H4KV'

    def _build_F0103309_xml(self, period_type, period_month):
        """Build the XML content for F0103309 matching Tax Cabinet format.

        Thin adapter: collects the wizard's own field values into a plain dict
        and delegates rendering to :meth:`_render_F0103309_xml`, so other modules
        (e.g. l10n_ua_fop) can produce the exact same declaration without
        duplicating the template.
        """
        return self._render_F0103309_xml({
            'taxpayer_tin': self.taxpayer_tin,
            'taxpayer_name': self.taxpayer_name,
            'taxpayer_address': self.taxpayer_address or '',
            'taxpayer_email': self.taxpayer_email or '',
            'taxpayer_phone': self.taxpayer_phone or '',
            'declaration_type': self.declaration_type,
            'tax_office_code': self.tax_office_id.code if self.tax_office_id else '',
            'tax_office_name': self.tax_office_id.name if self.tax_office_id else '',
            'quarter_marker': self._get_quarter_marker(),
            'period_type': period_type,
            'period_month': period_month,
            'year': self.year,
            'employee_count': self.employee_count,
            'activities': [(a.code, a.name) for a in self.activity_ids],
            'income_total': self.income_total,
            'tax_amount': self.tax_amount,
            'tax_paid_prev': self.tax_paid_prev,
            'tax_to_pay': self.tax_to_pay,
            'military_amount': self.military_amount,
            'military_paid_prev': self.military_paid_prev,
            'military_to_pay': self.military_to_pay,
        })

    @api.model
    def _render_F0103309_xml(self, vals):
        """Render F0103309 XML from an explicit values dict (module-agnostic).

        Kept stateless (reads only ``vals``, not ``self`` fields) so any module
        can build a single-tax declaration through the single canonical template.

        Expected keys: taxpayer_tin, taxpayer_name, taxpayer_address,
        taxpayer_email, taxpayer_phone, declaration_type, tax_office_code,
        tax_office_name, quarter_marker, period_type, period_month, year,
        employee_count, activities (list of (code, name) tuples), income_total,
        tax_amount, tax_paid_prev, tax_to_pay, military_amount,
        military_paid_prev, military_to_pay.
        """
        today = date.today()

        # Build activity codes XML (KVED). Table 1: G1S = code column, G2S = name
        # column. Indented to 8 spaces to match DECLARBODY nesting; no space
        # before ">" (matches the accepted CABINET sample).
        activities = vals.get('activities') or []
        activities_xml = ''
        for idx, (code, name) in enumerate(activities, 1):
            activities_xml += f'        <T1RXXXXG1S ROWNUM="{idx}">{self._escape_xml(code)}</T1RXXXXG1S>\n'
        for idx, (code, name) in enumerate(activities, 1):
            activities_xml += f'        <T1RXXXXG2S ROWNUM="{idx}">{self._escape_xml(name)}</T1RXXXXG2S>\n'

        # Get tax office codes
        tax_office_code = vals.get('tax_office_code') or ''
        c_reg = tax_office_code[:2] if len(tax_office_code) >= 2 else ''
        c_raj = tax_office_code[2:4] if len(tax_office_code) >= 4 else ''
        tax_office_name = vals.get('tax_office_name') or ''

        # Body reporting-period marker, derived from the (verified) PERIOD_TYPE.
        period_marker = F0103309_BODY_PERIOD_MARKER.get(
            str(vals.get('period_type')), 'HKV')

        xml = f'''<?xml version="1.0" encoding="windows-1251"?>
<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="F0103309.xsd">
    <DECLARHEAD>
        <TIN>{self._escape_xml(vals['taxpayer_tin'])}</TIN>
        <C_DOC>F01</C_DOC>
        <C_DOC_SUB>033</C_DOC_SUB>
        <C_DOC_VER>9</C_DOC_VER>
        <C_DOC_TYPE>{vals['declaration_type']}</C_DOC_TYPE>
        <C_DOC_CNT>1</C_DOC_CNT>
        <C_REG>{c_reg}</C_REG>
        <C_RAJ>{c_raj}</C_RAJ>
        <PERIOD_MONTH>{vals['period_month']}</PERIOD_MONTH>
        <PERIOD_TYPE>{vals['period_type']}</PERIOD_TYPE>
        <PERIOD_YEAR>{vals['year']}</PERIOD_YEAR>
        <C_STI_ORIG>{tax_office_code}</C_STI_ORIG>
        <C_DOC_STAN>1</C_DOC_STAN>
        <LINKED_DOCS xsi:nil="true"/>
        <D_FILL>{today.strftime('%d%m%Y')}</D_FILL>
        <SOFTWARE>{F0103309_SOFTWARE}</SOFTWARE>
    </DECLARHEAD>
    <DECLARBODY>
        <HZ>1</HZ>
        <{period_marker}>1</{period_marker}>
        <HZY>{vals['year']}</HZY>
        <HSTI>{self._escape_xml(tax_office_name)}</HSTI>
        <HNAME>{self._escape_xml(vals['taxpayer_name'])}</HNAME>
        <HLOC>{self._escape_xml(vals.get('taxpayer_address') or '')}</HLOC>
        <HEMAIL>{self._escape_xml(vals.get('taxpayer_email') or '')}</HEMAIL>
        <HTEL>{self._escape_xml(vals.get('taxpayer_phone') or '')}</HTEL>
        <HTIN>{self._escape_xml(vals['taxpayer_tin'])}</HTIN>
        <HNACTL>{vals.get('employee_count') or 0}</HNACTL>
{activities_xml}        <R006G3>{self._format_amount(vals['income_total'])}</R006G3>
        <R008G3>{self._format_amount(vals['income_total'])}</R008G3>
        <R011G3>{self._format_amount(vals['tax_amount'])}</R011G3>
        <R012G3>{self._format_amount(vals['tax_amount'])}</R012G3>
        <R013G3>{self._format_amount(vals['tax_paid_prev'])}</R013G3>
        <R0141G3>{self._format_amount(vals['tax_to_pay'])}</R0141G3>
        <R014G3>{self._format_amount(vals['tax_to_pay'])}</R014G3>
        <R023G3>{self._format_amount(vals['military_amount'])}</R023G3>
        <R024G3>{self._format_amount(vals['military_paid_prev'])}</R024G3>
        <R025G3>{self._format_amount(vals['military_to_pay'])}</R025G3>
        <T2RXXXXG2S ROWNUM="1" xsi:nil="true"/>
        <HFILL>{today.strftime('%d%m%Y')}</HFILL>
        <HKEXECUTOR>{self._escape_xml(vals['taxpayer_tin'])}</HKEXECUTOR>
        <HBOS>{self._escape_xml(vals['taxpayer_name'])}</HBOS>
    </DECLARBODY>
</DECLAR>'''
        return xml

    def _format_amount(self, value):
        """Format amount for XML (2 decimal places, no thousands separator)."""
        if not value:
            return '0.00'
        return f'{value:.2f}'


class L10nUaTaxDocumentWizardActivity(models.TransientModel):
    """Activity codes (KVED) for tax declarations."""
    _name = 'l10n_ua.tax.document.wizard.activity'
    _description = 'Tax Document Wizard Activity Code'

    wizard_id = fields.Many2one(
        'l10n_ua.tax.document.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    kved_id = fields.Many2one(
        'l10n_ua.kved',
        string='KVED',
        required=True,
        domain=[('level', '=', 4)],  # Only class-level codes (e.g., 62.01)
    )
    code = fields.Char(
        string='Code',
        related='kved_id.code',
        store=True,
    )
    name = fields.Char(
        string='Name',
        related='kved_id.name',
        store=True,
    )
    is_primary = fields.Boolean(
        string='Primary',
        default=False,
    )
