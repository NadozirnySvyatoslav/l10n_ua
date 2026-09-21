import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nUaTaxDocument(models.Model):
    """Base model for Ukrainian tax documents (declarations, reports, etc.)"""
    _name = 'l10n_ua.tax.document'
    _description = 'Tax Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'document_date desc, id desc'

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
    )
    document_type_id = fields.Many2one(
        'l10n_ua.tax.document.type',
        string='Document Type',
        required=True,
        tracking=True,
    )
    document_number = fields.Char(
        string='Document Number',
        tracking=True,
    )
    document_date = fields.Date(
        string='Document Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    # Period info
    year = fields.Integer(
        string='Year',
        default=lambda self: fields.Date.context_today(self).year,
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
    )
    period_id = fields.Many2one(
        'l10n_ua.tax.period',
        string='Tax Period',
        help='Link to tax period for reporting',
    )

    # Company / FOP
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    taxpayer_code = fields.Char(
        string='Taxpayer Code',
        help='EDRPOU or RNOKPP',
    )

    # File attachments
    file_xml = fields.Binary(
        string='XML File',
        attachment=True,
    )
    file_xml_name = fields.Char(
        string='XML Filename',
    )
    file_pdf = fields.Binary(
        string='PDF File',
        attachment=True,
    )
    file_pdf_name = fields.Char(
        string='PDF Filename',
    )

    # Computed fields for viewing XML
    file_xml_content = fields.Text(
        string='XML Content',
        compute='_compute_file_xml_content',
        inverse='_inverse_file_xml_content',
    )

    @api.depends('file_xml')
    def _compute_file_xml_content(self):
        for record in self:
            if record.file_xml:
                try:
                    content = base64.b64decode(record.file_xml)
                    # Try different encodings
                    for encoding in ['utf-8', 'windows-1251', 'cp1251']:
                        try:
                            record.file_xml_content = content.decode(encoding)
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        record.file_xml_content = content.decode('utf-8', errors='replace')
                except Exception:
                    record.file_xml_content = False
            else:
                record.file_xml_content = False

    def _inverse_file_xml_content(self):
        for record in self:
            if record.file_xml_content:
                record.file_xml = base64.b64encode(record.file_xml_content.encode('utf-8')).decode()
            else:
                record.file_xml = False

    # Status
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('prepared', 'Prepared'),
            ('submitted', 'Submitted'),
            ('accepted', 'Accepted'),
            ('rejected', 'Rejected'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )
    status_message = fields.Text(
        string='Status Message',
        help='Message from tax authority',
    )

    # Notes
    notes = fields.Text(
        string='Notes',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('taxpayer_code') and vals.get('company_id'):
                company = self.env['res.company'].browse(vals['company_id'])
                vals['taxpayer_code'] = company.vat or company.company_registry
        return super().create(vals_list)

    def action_prepare(self):
        """Mark document as prepared (XML generated)."""
        self.write({'state': 'prepared'})

    def action_mark_submitted(self):
        """Mark document as submitted to tax authority."""
        self.write({'state': 'submitted'})

    def action_mark_accepted(self):
        """Mark document as accepted by tax authority."""
        self.write({'state': 'accepted'})

    def action_mark_rejected(self):
        """Mark document as rejected by tax authority."""
        self.write({'state': 'rejected'})

    def action_reset_draft(self):
        """Reset document to draft state."""
        self.write({'state': 'draft'})

    def action_fill_data(self):
        """Open wizard to fill document data based on document type."""
        self.ensure_one()
        if not self.document_type_id:
            raise UserError(_("Please select a document type first."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Fill Document Data'),
            'res_model': 'l10n_ua.tax.document.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_document_id': self.id,
                'default_document_type_id': self.document_type_id.id,
                'default_company_id': self.company_id.id,
                'default_year': self.year,
                'default_period': self.period,
            },
        }

    def _generate_filename(self):
        """Generate filename for tax document.

        Format according to Order №729:
        [J/F][CCCC][SSS]_[RRRRRRRRR]_[YYYYMMDDHHMMSS]_[N].xml
        """
        self.ensure_one()

        if self.file_xml_name:
            return self.file_xml_name

        from datetime import datetime

        taxpayer_code = self.taxpayer_code or ''
        entity_type = 'F' if len(taxpayer_code) == 10 else 'J'

        doc_code = '0103309'
        if self.document_type_id and self.document_type_id.code:
            doc_code = self.document_type_id.code.replace('F', '').replace('J', '')

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{entity_type}{doc_code}_{taxpayer_code}_{timestamp}_1.xml"

        return filename
