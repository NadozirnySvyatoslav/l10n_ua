import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# The payslip batch API takes up to 1000 employees per request.
MONO_PAYSLIP_BATCH = 1000

MONO_IMPORT_STATUS = {
    'LOADING': 'loading',
    'LOADED': 'loaded',
    'FAILED': 'failed',
    'SENT': 'sent',
    'DELETED': 'deleted',
}


def _amount(value):
    return '%.2f' % (value or 0.0)


class L10nUaMonoPayslipImport(models.Model):
    """Payslips of a period published in the monobank app.

    Accruals and deductions of each payslip go as free-form attributes
    (`POST /ext/v1/payslips/batch`, up to 1000 employees per call; calls of
    one period make one import), then the import is published to the
    employees (`/ext/v1/payslip-imports/send`). Employees monobank does not
    know as salary contacts are listed back as failed.
    """
    _name = 'l10n_ua.mono.payslip.import'
    _description = 'monobank Payslip Import'
    _inherit = ['mail.thread']
    _order = 'period desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    config_id = fields.Many2one(
        'l10n_ua.bank.sync.config', string='monobank Connection', required=True,
        domain="[('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),"
               " ('company_id', '=', company_id)]")
    period = fields.Char(
        required=True, size=7, help='Salary period, YYYY-MM.')
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Payslip Batch')
    payslip_ids = fields.Many2many('hr.payslip', string='Payslips')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('loading', 'Loading'),
        ('loaded', 'Uploaded'),
        ('failed', 'Failed'),
        ('sent', 'Published'),
        ('deleted', 'Deleted'),
    ], default='draft', required=True, tracking=True, copy=False)
    total_employees = fields.Integer(readonly=True, copy=False)
    success_employees = fields.Integer(readonly=True, copy=False)
    failed_employees = fields.Integer(readonly=True, copy=False)
    failed_details = fields.Text(
        string='Not Uploaded', readonly=True, copy=False,
        help='Employees monobank could not match: add them to the salary '
             'contacts and upload again.')
    employees_sent = fields.Integer(readonly=True, copy=False)

    @api.depends('period', 'config_id')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Payslips %(period)s (%(config)s)',
                         period=rec.period or '', config=rec.config_id.name or '')

    @api.constrains('period')
    def _check_period(self):
        for rec in self:
            try:
                fields.Date.from_string(rec.period + '-01')
            except (TypeError, ValueError):
                raise UserError(_('Period must be YYYY-MM, not %s.', rec.period))

    def _slips(self):
        self.ensure_one()
        return self.payslip_ids.filtered(lambda s: s.state == 'done')

    @api.model
    def _payslip_attributes(self, slip):
        """The lines of a payslip in the monobank app, in display order."""
        rows = []
        if slip.worked_days:
            rows.append((_('Worked days'), str(slip.worked_days), _('days')))
        if slip.worked_hours:
            rows.append((_('Worked hours'), '%g' % slip.worked_hours, _('hours')))
        for accrual in slip.accrual_ids.sorted('sequence'):
            rows.append((accrual.accrual_type_id.name or _('Accrual'),
                         _amount(accrual.amount), _('UAH')))
        rows.append((_('Total accrued'), _amount(slip.gross_salary), _('UAH')))
        if slip.pdfo_amount:
            rows.append((_('Personal income tax'), _amount(slip.pdfo_amount), _('UAH')))
        if slip.military_tax_amount:
            rows.append((_('Military tax'), _amount(slip.military_tax_amount), _('UAH')))
        for deduction in slip.deduction_ids.sorted('sequence'):
            if deduction.deduction_type_id.category == 'tax':
                continue
            rows.append((deduction.deduction_type_id.name or _('Deduction'),
                         _amount(deduction.amount), _('UAH')))
        rows.append((_('Total deducted'), _amount(slip.total_deductions), _('UAH')))
        rows.append((_('To be paid'), _amount(slip.net_salary), _('UAH')))
        return [{
            'attributeName': name,
            'value': value,
            'sortOrder': order,
            'attributeSuffix': suffix,
        } for order, (name, value, suffix) in enumerate(rows, start=1)]

    def _employees_payload(self, slips):
        """One entry per employee; several payslips of one employee in the
        period (a correction, a second job) are merged in order."""
        by_ident, missing = {}, []
        # The app shows the payslip to the employee in Ukrainian.
        lang = 'uk_UA' if self.env['res.lang'].search_count(
            [('code', '=', 'uk_UA')]) else self.env.lang
        for slip in slips.sorted(lambda s: (s.employee_id.id, s.date_from or fields.Date.today(), s.id)):
            ident = slip.employee_id._l10n_ua_mono_identification()
            if not ident:
                missing.append(slip.employee_id.name)
                continue
            attributes = self.with_context(lang=lang)._payslip_attributes(slip)
            if ident in by_ident:
                offset = len(by_ident[ident])
                for attr in attributes:
                    attr['sortOrder'] += offset
                by_ident[ident].extend(attributes)
            else:
                by_ident[ident] = attributes
        if missing:
            raise UserError(_('No RNOKPP or passport for: %s', ', '.join(missing)))
        return [{'identification': ident, 'attributes': attrs}
                for ident, attrs in by_ident.items()]

    def _store_failures(self, failed):
        employees = self.env['hr.employee']
        by_ident = {}
        for slip in self.payslip_ids:
            by_ident.setdefault(slip.employee_id._l10n_ua_mono_identification(),
                                slip.employee_id)
        details = []
        for item in failed:
            ident = item.get('identification') or ''
            employee = by_ident.get(ident, employees)
            reason = item.get('reason') or ''
            details.append('%s %s — %s' % (
                ident, employee.name or '',
                _('not among the salary contacts') if reason == 'CONTACT_NOT_FOUND'
                else reason))
        self.write({
            'failed_details': '\n'.join(details) or False,
        })

    def action_upload(self):
        """Upload the payslips of the period to monobank."""
        self.ensure_one()
        if self.state in ('sent',):
            raise UserError(_('The payslips are already published to the employees.'))
        slips = self._slips()
        if not slips:
            raise UserError(_('No closed (Done) payslips to upload.'))
        self._check_period()
        employees = self._employees_payload(slips)
        failed, overall = [], {}
        for start in range(0, len(employees), MONO_PAYSLIP_BATCH):
            result = self.config_id._mono_corp_request(
                '/ext/v1/payslips/batch', method='POST', payload={
                    'period': self.period,
                    'employees': employees[start:start + MONO_PAYSLIP_BATCH],
                }) or {}
            result = result.get('result', result)
            failed.extend(result.get('failedEmployees') or [])
            overall = result.get('overallStats') or overall
        self.write({
            'state': 'loaded',
            'total_employees': overall.get('totalEmployees', len(employees)),
            'success_employees': overall.get(
                'totalSuccessEmployees', len(employees) - len(failed)),
            'failed_employees': overall.get('totalFailedEmployees', len(failed)),
        })
        self._store_failures(failed)
        body = _('Uploaded to monobank: %(ok)d of %(total)d employee(s).',
                 ok=self.success_employees, total=self.total_employees)
        if self.failed_details:
            body += '\n' + _('Not uploaded:') + '\n' + self.failed_details
        self.message_post(body=body)
        return True

    def action_refresh_status(self):
        self.ensure_one()
        result = self.config_id._mono_corp_request(
            '/ext/v1/payslip-imports/status', params={'period': self.period}) or {}
        result = result.get('result', result)
        vals = {
            'total_employees': result.get('totalEmployees', self.total_employees),
            'success_employees': result.get('totalSuccessEmployees', self.success_employees),
            'failed_employees': result.get('totalFailedEmployees', self.failed_employees),
        }
        state = MONO_IMPORT_STATUS.get(result.get('status'))
        if state:
            vals['state'] = state
        self.write(vals)
        if 'failedEmployees' in result:
            self._store_failures(result.get('failedEmployees') or [])
        return True

    def action_send(self):
        """Publish the uploaded payslips to the employees in the app."""
        self.ensure_one()
        if self.state != 'loaded':
            raise UserError(_('Upload the payslips first.'))
        result = self.config_id._mono_corp_request(
            '/ext/v1/payslip-imports/send', method='POST',
            params={'period': self.period}) or {}
        result = result.get('result', result)
        self.write({'state': 'sent', 'employees_sent': result.get('employeesSent') or 0})
        self.message_post(body=_(
            'Payslips published in the monobank app to %d employee(s).',
            self.employees_sent))
        return True

    def action_delete_import(self):
        """Delete the whole import of the period in monobank."""
        self.ensure_one()
        self.config_id._mono_corp_request(
            '/ext/v1/payslip-imports', method='DELETE',
            params={'period': self.period})
        self.write({'state': 'deleted', 'failed_details': False})
        self.message_post(body=_('Import of %s deleted in monobank.', self.period))
        return True

    def action_sync_contacts(self):
        self.ensure_one()
        employees = self.payslip_ids.mapped('employee_id')
        if not employees:
            raise UserError(_('No employees.'))
        report = employees._l10n_ua_mono_sync_contacts(self.config_id)
        self.message_post(body=employees._l10n_ua_mono_contacts_report(report))
        return True

    def _download_pdf(self, employee):
        """The payslip PDF of an employee from monobank, as an attachment."""
        self.ensure_one()
        ident = employee._l10n_ua_mono_identification()
        if not ident:
            raise UserError(_('No RNOKPP or passport for %s.', employee.name))
        response = self.config_id._mono_corp_request(
            '/ext/v1/payslips/pdf',
            params={'identification': ident, 'period': self.period}, raw=True)
        return self.env['ir.attachment'].create({
            'name': 'monobank_payslip_%s_%s.pdf' % (self.period, ident),
            'datas': base64.b64encode(response.content),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def action_mono_payslip_import(self):
        """Open (or start) the monobank payslip import of the batch."""
        self.ensure_one()
        Import = self.env['l10n_ua.mono.payslip.import']
        record = Import.search([('payslip_run_id', '=', self.id),
                                ('state', '!=', 'deleted')], limit=1)
        if not record:
            config = self.env['l10n_ua.bank.sync.config']._mono_corp_config_for_iban(
                self.company_id.payroll_bank_account_id.acc_number, self.company_id)
            if not config:
                config = self.env['l10n_ua.bank.sync.config'].search([
                    ('provider', '=', 'mono'), ('mono_api_type', '=', 'corporate'),
                    ('company_id', '=', self.company_id.id)], limit=1)
            if not config:
                raise UserError(_('No monobank corporate API connection for %s.',
                                  self.company_id.name))
            record = Import.create({
                'company_id': self.company_id.id,
                'config_id': config.id,
                'period': (self.date_end or self.date_start).strftime('%Y-%m'),
                'payslip_run_id': self.id,
                'payslip_ids': [(6, 0, self.slip_ids.ids)],
            })
        return {
            'type': 'ir.actions.act_window',
            'res_model': Import._name,
            'res_id': record.id,
            'view_mode': 'form',
        }


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_mono_payslip_pdf(self):
        """Download the payslip as monobank shows it in the app."""
        self.ensure_one()
        imports = self.env['l10n_ua.mono.payslip.import'].search([
            ('payslip_ids', 'in', self.ids),
            ('state', 'in', ('loaded', 'sent')),
        ], limit=1)
        if not imports:
            raise UserError(_('The payslip has not been uploaded to monobank.'))
        attachment = imports._download_pdf(self.employee_id)
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
