import base64
import logging
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaTaxDocumentWizard(models.TransientModel):
    """
    Base wizard for filling tax document data.

    This wizard provides common functionality for all tax document types.
    Specific document types (F0103309, etc.) should extend this wizard
    and implement their own _generate_xml_<code>() method.
    """
    _name = 'l10n_ua.tax.document.wizard'
    _description = 'Tax Document Data Wizard'

    document_id = fields.Many2one(
        'l10n_ua.tax.document',
        string='Document',
        required=True,
        readonly=True,
    )
    document_type_id = fields.Many2one(
        'l10n_ua.tax.document.type',
        string='Document Type',
        required=True,
        readonly=True,
    )
    document_type_code = fields.Char(
        string='Document Type Code',
        related='document_type_id.code',
        readonly=True,
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: date.today().year,
    )
    period = fields.Selection(
        selection=[
            ('01', 'January'),
            ('02', 'February'),
            ('03', 'March'),
            ('04', 'April'),
            ('05', 'May'),
            ('06', 'June'),
            ('07', 'July'),
            ('08', 'August'),
            ('09', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
            ('q1', 'Q1'),
            ('q2', 'Q2'),
            ('q3', 'Q3'),
            ('q4', 'Q4'),
            ('h1', 'H1'),
            ('h2', 'H2'),
            ('year', 'Year'),
        ],
        string='Period',
        required=True,
    )

    # Common header fields for all tax documents
    taxpayer_tin = fields.Char(
        string='Taxpayer TIN (РНОКПП/ЄДРПОУ)',
        required=True,
    )
    taxpayer_name = fields.Char(
        string='Taxpayer Name',
        required=True,
    )
    taxpayer_address = fields.Char(
        string='Address',
    )
    taxpayer_phone = fields.Char(
        string='Phone',
    )
    taxpayer_email = fields.Char(
        string='Email',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Pre-fill from company
        if 'company_id' in res:
            company = self.env['res.company'].browse(res['company_id'])
            if company:
                res['taxpayer_tin'] = company.vat or company.edrpou or ''
                res['taxpayer_name'] = company.name or ''
                res['taxpayer_address'] = self._format_company_address(company)
                res['taxpayer_phone'] = company.phone or ''
                res['taxpayer_email'] = company.email or ''

        return res

    def _format_company_address(self, company):
        """Format company address for tax documents."""
        parts = []
        if company.zip:
            parts.append(company.zip)
        if company.state_id:
            parts.append(company.state_id.name)
        if company.city:
            parts.append(company.city)
        if company.street:
            parts.append(company.street)
        if company.street2:
            parts.append(company.street2)
        return ', '.join(parts)

    def action_generate(self):
        """Generate XML document based on document type."""
        self.ensure_one()

        # Find and call the specific generation method
        method_name = f'_generate_xml_{self.document_type_code}'
        generator = getattr(self, method_name, None)
        if generator:
            xml_content, filename = generator()
        else:
            raise UserError(_(
                "Document type '%s' is not supported yet. "
                "Please install the corresponding module (l10n_ua_tax_%s)."
            ) % (self.document_type_id.name, self.document_type_code))

        # Update the document
        self.document_id.write({
            'file_xml': base64.b64encode(xml_content.encode('windows-1251')).decode(),
            'file_xml_name': filename,
            'year': self.year,
            'period': self.period,
            'taxpayer_code': self.taxpayer_tin,
        })

        # Update document name if empty
        if not self.document_id.name or self.document_id.name == _('New'):
            self.document_id.name = f"{self.document_type_id.name} {self.year}/{self.period}"

        return {'type': 'ir.actions.act_window_close'}

    def _get_period_type(self):
        """Get period type code for XML (1=month, 2=quarter, 3=half-year, 4=9months, 5=year)."""
        if self.period in ('01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'):
            return '1'  # Monthly
        elif self.period in ('q1', 'q2', 'q3', 'q4'):
            return '2'  # Quarterly
        elif self.period in ('h1', 'h2'):
            return '3'  # Half-year
        else:
            return '5'  # Annual

    def _get_period_month(self):
        """Get period month number for XML."""
        period_map = {
            '01': '1', '02': '2', '03': '3', '04': '4', '05': '5', '06': '6',
            '07': '7', '08': '8', '09': '9', '10': '10', '11': '11', '12': '12',
            'q1': '3', 'q2': '6', 'q3': '9', 'q4': '12',
            'h1': '6', 'h2': '12',
            'year': '12',
        }
        return period_map.get(self.period, '12')

    def _escape_xml(self, value):
        """Escape special characters for XML."""
        if not value:
            return ''
        return (str(value)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))
