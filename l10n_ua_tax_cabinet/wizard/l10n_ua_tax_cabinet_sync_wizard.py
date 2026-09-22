import logging
import xml.etree.ElementTree as ET
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class L10nUaTaxCabinetSyncWizard(models.TransientModel):
    _name = 'l10n_ua.tax.cabinet.sync.wizard'
    _inherit = ['l10n_ua.sign.mixin']
    _description = 'Tax Cabinet Sync Wizard'

    mode = fields.Selection(
        selection=[
            ('upload', 'Upload Documents'),
            ('sync', 'Sync from Cabinet'),
        ],
        string='Mode',
        default='upload',
        required=True,
    )

    # Upload mode fields
    file_ids = fields.One2many(
        'l10n_ua.tax.cabinet.sync.wizard.file',
        'wizard_id',
        string='Files',
    )

    # Sync mode fields
    config_id = fields.Many2one(
        'l10n_ua.tax.cabinet.config',
        string='Configuration',
    )
    sync_type = fields.Selection(
        selection=[
            ('reported', 'Reported Documents'),
            ('incoming', 'Incoming Correspondence'),
            ('sent', 'Sent Correspondence'),
        ],
        string='Document Type',
        default='reported',
    )
    year = fields.Integer(
        string='Year',
        default=lambda self: fields.Date.today().year,
    )
    month = fields.Selection(
        selection=[
            ('1', 'January'),
            ('2', 'February'),
            ('3', 'March'),
            ('4', 'April'),
            ('5', 'May'),
            ('6', 'June'),
            ('7', 'July'),
            ('8', 'August'),
            ('9', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
        ],
        string='Month',
        default=lambda self: str(fields.Date.today().month),
    )

    # Common
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            config = self.env['l10n_ua.tax.cabinet.config'].search([
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if config:
                self.config_id = config

    @api.onchange('mode')
    def _onchange_mode(self):
        if self.mode == 'sync' and not self.config_id:
            config = self.env['l10n_ua.tax.cabinet.config'].search([
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if config:
                self.config_id = config

    def action_process(self):
        """Process based on selected mode."""
        self.ensure_one()
        if self.mode == 'upload':
            return self._process_upload()
        elif self.mode == 'sync':
            return self._process_sync()

    def _process_upload(self):
        """Process uploaded files and create documents."""
        self.ensure_one()
        if not self.file_ids:
            raise UserError(_("Please add files to upload"))

        created_docs = self.env['l10n_ua.tax.document']

        for file_line in self.file_ids:
            doc_vals = self._prepare_document_vals(file_line)
            doc = self.env['l10n_ua.tax.document'].create(doc_vals)
            created_docs |= doc
            _logger.info("Created tax document: %s", doc.name)

        # Show created documents
        if len(created_docs) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Tax Document'),
                'res_model': 'l10n_ua.tax.document',
                'view_mode': 'form',
                'res_id': created_docs.id,
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Tax Documents'),
                'res_model': 'l10n_ua.tax.document',
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_docs.ids)],
            }

    def _prepare_document_vals(self, file_line):
        """Prepare values for document creation from uploaded file."""
        vals = {
            'name': file_line.name or file_line.filename,
            'document_type_id': file_line.document_type_id.id,
            'document_date': file_line.document_date or fields.Date.today(),
            'year': file_line.year,
            'period': file_line.period,
            'company_id': self.company_id.id,
            'source': 'manual',
        }

        # Determine file type and attach
        filename = file_line.filename.lower() if file_line.filename else ''
        if filename.endswith('.xml'):
            vals['file_xml'] = file_line.file
            vals['file_xml_name'] = file_line.filename
            # Try to parse XML for additional info
            self._parse_xml_document(file_line.file, vals)
        elif filename.endswith('.pdf'):
            vals['file_pdf'] = file_line.file
            vals['file_pdf_name'] = file_line.filename
        else:
            # Treat as XML by default
            vals['file_xml'] = file_line.file
            vals['file_xml_name'] = file_line.filename

        return vals

    def _parse_xml_document(self, file_content, vals):
        """Try to parse XML and extract document info."""
        try:
            xml_data = file_content.content
            root = ET.fromstring(xml_data)

            # Try to find common Ukrainian tax XML elements
            # HTIN - taxpayer code
            htin = root.find('.//HTIN') or root.find('.//TIN')
            if htin is not None and htin.text:
                vals['taxpayer_code'] = htin.text

            # HNAME - document name
            hname = root.find('.//HNAME')
            if hname is not None and hname.text:
                vals['name'] = hname.text

            # HNUM - document number
            hnum = root.find('.//HNUM')
            if hnum is not None and hnum.text:
                vals['document_number'] = hnum.text

            # Period info
            hper = root.find('.//HPER')
            if hper is not None and hper.text:
                period_map = {
                    '1': '01', '2': '02', '3': '03', '4': '04',
                    '5': '05', '6': '06', '7': '07', '8': '08',
                    '9': '09', '10': '10', '11': '11', '12': '12',
                }
                vals['period'] = period_map.get(hper.text, hper.text)

            hperu = root.find('.//HPERU')  # Period type
            if hperu is not None and hperu.text:
                period_type_map = {
                    '1': None,  # month - use HPER
                    '2': 'q1',  # quarter
                    '3': 'h1',  # half-year
                    '4': 'year',  # year
                }
                if hperu.text in period_type_map and period_type_map[hperu.text]:
                    vals['period'] = period_type_map[hperu.text]

            hreg = root.find('.//HREG')  # Year
            if hreg is not None and hreg.text:
                try:
                    vals['year'] = int(hreg.text)
                except ValueError:
                    pass

        except Exception as e:
            _logger.warning("Could not parse XML document: %s", str(e))

    def _process_sync(self):
        """Синхронізація: браузер підписує код платника, сервер забирає документи.

        Ключ і пароль сервера не торкаються (#324).
        """
        self.ensure_one()

        if not self.config_id:
            raise UserError(_("Please select or create a Tax Cabinet configuration first."))

        return self.action_kep_sign(mode='sync')

    # --- контракт l10n_ua.sign.mixin ---

    def kep_prepare_signing(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError(_("Please select or create a Tax Cabinet configuration first."))
        return {
            'auth_subject': self.config_id.taxpayer_code,
            'submit_label': _('Синхронізувати'),
            'documents': [],
            'close_action': self.env['ir.actions.act_window']._for_xml_id(
                'l10n_ua_tax.l10n_ua_tax_document_action'),
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        config = self.config_id
        Document = self.env['l10n_ua.tax.document']

        if self.sync_type == 'incoming':
            count = Document._sync_incoming_documents(config, auth_signature=auth_signature)
        elif self.sync_type == 'sent':
            count = Document._sync_sent_documents(config, auth_signature=auth_signature)
        else:
            month = int(self.month or fields.Date.today().month)
            count = Document._sync_reported_documents(
                config, self.year, month, auth_signature=auth_signature)

        # Службова позначка; писати саму конфігурацію має право лише менеджер.
        config.sudo().last_sync_date = fields.Datetime.now()
        return {'receipt': _('Імпортовано документів: %d') % count}


class L10nUaTaxCabinetSyncWizardFile(models.TransientModel):
    _name = 'l10n_ua.tax.cabinet.sync.wizard.file'
    _description = 'Tax Cabinet Sync Wizard File'

    wizard_id = fields.Many2one(
        'l10n_ua.tax.cabinet.sync.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    file = fields.Binary(
        string='File',
        required=True,
        attachment=False,
    )
    filename = fields.Char(
        string='Filename',
    )
    name = fields.Char(
        string='Document Name',
        help='Leave empty to extract from file',
    )
    document_type_id = fields.Many2one(
        'l10n_ua.tax.document.type',
        string='Document Type',
        required=True,
    )
    document_date = fields.Date(
        string='Document Date',
        default=fields.Date.today,
    )
    year = fields.Integer(
        string='Year',
        default=lambda self: fields.Date.today().year,
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
