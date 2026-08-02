import base64
import io
import zipfile

from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .dbf import build_dbf


class HrPayslipBankExport(models.TransientModel):
    """Майстер формування зарплатного файлу для клієнт-банку (#152).

    Збирає закриті розрахункові листки за період (або з обраної відомості),
    валідує реквізити й суми та формує один пакетний файл (XML або DBF) для
    масової виплати: РНОКПП, ПІБ, IBAN, сума до виплати, призначення платежу.
    """
    _name = 'hr.payslip.bank.export'
    _description = 'Payroll Bank File Export'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    payslip_run_id = fields.Many2one(
        'hr.payslip.run', string='Payslip Batch',
        help='Якщо задано — беруться листки цієї відомості; інакше — за період.')
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')
    file_format = fields.Selection(
        [('xml', 'XML'), ('dbf', 'DBF'),
         ('ifobs', 'iFOBS (Укргазбанк та ін.)'),
         ('ibank2', 'iBank 2 UA (VST Bank та ін.)')],
        string='Format', required=True,
        default=lambda self: self.env.company.payroll_bank_file_format or 'xml')
    payer_account_id = fields.Many2one(
        'res.partner.bank', string='Payer Account',
        default=lambda self: self.env.company.payroll_bank_account_id)
    transit_account_id = fields.Many2one(
        'res.partner.bank', string='Transit Account',
        default=lambda self: self.env.company.payroll_transit_account_id,
        help='Транзитний рахунок зарплатного проєкту (iFOBS).')
    salary_project_code = fields.Char(
        string='Salary Project Code (ЗКП)',
        default=lambda self: self.env.company.payroll_salary_project_code)
    accrual_name = fields.Char(
        string='Accrual Type',
        default=lambda self: self.env.company.payroll_accrual_name
        or 'Заробітна плата')
    payment_purpose = fields.Char(
        string='Payment Purpose',
        default=lambda self: self.env.company.payroll_payment_purpose
        or 'Заробітна плата за {period}')

    file_data = fields.Binary(string='File', readonly=True, attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)
    state = fields.Selection(
        [('choose', 'Choose'), ('done', 'Done')], default='choose')

    @api.onchange('payslip_run_id')
    def _onchange_run(self):
        if self.payslip_run_id:
            self.date_from = self.payslip_run_id.date_start
            self.date_to = self.payslip_run_id.date_end

    def _get_payslips(self):
        self.ensure_one()
        if self.payslip_run_id:
            slips = self.payslip_run_id.slip_ids
        else:
            if not (self.date_from and self.date_to):
                raise UserError(_('Вкажіть період або відомість.'))
            slips = self.env['hr.payslip'].search([
                ('company_id', '=', self.company_id.id),
                ('date_from', '>=', self.date_from),
                ('date_to', '<=', self.date_to),
            ])
        return slips.filtered(lambda s: s.state == 'done')

    def _period_label(self):
        d = self.date_to or (self.payslip_run_id and self.payslip_run_id.date_end)
        return d.strftime('%m.%Y') if d else ''

    def _build_rows(self, slips):
        """Побудувати рядки виплат + валідація реквізитів і сум."""
        period = self._period_label()
        rows = []
        missing_account = []
        skipped_zero = 0
        for slip in slips:
            employee = slip.employee_id
            amount = round(slip.net_salary, 2)
            if amount <= 0:
                skipped_zero += 1
                continue
            # One payment per employee: the native primary account is the one
            # ranked first in salary_distribution, or the only account when no
            # distribution is set.
            bank = employee.primary_bank_account_id
            if not bank or not bank.acc_number:
                missing_account.append(employee.name)
                continue
            purpose = (self.payment_purpose or '').format(
                period=period, employee=employee.name or '',
                rnokpp=employee.rnokpp or '')
            rows.append({
                'rnokpp': employee.rnokpp or '',
                'name': employee.name or '',
                'account': (bank.acc_number or '').replace(' ', ''),
                'amount': amount,
                'purpose': purpose,
            })
        if missing_account:
            raise UserError(_(
                'No bank account (IBAN) for employees:\n- %s'
            ) % '\n- '.join(missing_account))
        if not rows:
            raise UserError(_(
                'Немає рядків для виплати (усі суми нульові або немає '
                'закритих листків за період).'))
        return rows, skipped_zero

    def _render_xml(self, rows):
        period = self._period_label()
        total = sum(r['amount'] for r in rows)
        root = etree.Element('PaymentPackage')
        root.set('company', self.company_id.name or '')
        root.set('payer_account',
                 (self.payer_account_id.acc_number or '').replace(' ', ''))
        root.set('period', period)
        root.set('count', str(len(rows)))
        root.set('total', f'{total:.2f}')
        for r in rows:
            p = etree.SubElement(root, 'Payment')
            etree.SubElement(p, 'Rnokpp').text = r['rnokpp']
            etree.SubElement(p, 'Name').text = r['name']
            etree.SubElement(p, 'Account').text = r['account']
            etree.SubElement(p, 'Amount').text = f"{r['amount']:.2f}"
            etree.SubElement(p, 'Purpose').text = r['purpose']
        return etree.tostring(
            root, xml_declaration=True, encoding='windows-1251', pretty_print=True)

    def _render_dbf(self, rows):
        field_defs = [
            ('NN', 'N', 5, 0),
            ('OKPO', 'C', 10, 0),
            ('NAME', 'C', 60, 0),
            ('IBAN', 'C', 34, 0),
            ('SUMMA', 'N', 15, 2),
            ('DETAILS', 'C', 160, 0),
        ]
        dbf_rows = []
        for i, r in enumerate(rows, start=1):
            dbf_rows.append({
                'NN': i,
                'OKPO': r['rnokpp'],
                'NAME': r['name'],
                'IBAN': r['account'],
                'SUMMA': r['amount'],
                'DETAILS': r['purpose'],
            })
        return build_dbf(field_defs, dbf_rows)

    # --- Реквізити платника для банк-специфічних форматів ---
    def _company_edrpou(self):
        company = self.company_id
        return (getattr(company, 'company_registry', False)
                or (company.vat or '').replace('UA', '').strip() or '')

    def _payer_mfo(self):
        bank = self.payer_account_id.bank_id
        return getattr(bank, 'ua_mfo', False) or ''

    @staticmethod
    def _split_name(full_name):
        """Розбити ПІБ на прізвище / ім'я / по батькові (best-effort)."""
        parts = (full_name or '').split()
        last = parts[0] if parts else ''
        first = parts[1] if len(parts) > 1 else ''
        middle = ' '.join(parts[2:]) if len(parts) > 2 else ''
        return last, first, middle

    def _render_ifobs(self, rows):
        """iFOBS.eSalary — ZIP з ScheduleInfo.dbf (1 запис) + Amounts.dbf.

        Структура полів за офіційним описом форматів iFOBS.eSalary
        (windows-1251). Набір полів може відрізнятися залежно від банку —
        звірте з документом «Опис форматів» вашого банку.
        """
        total = sum(r['amount'] for r in rows)
        transit = (self.transit_account_id.acc_number or '').replace(' ', '')
        debit = (self.payer_account_id.acc_number or '').replace(' ', '')
        sched_fields = [
            ('SHED_DATE', 'D', 8, 0), ('SCHED_NO', 'C', 10, 0),
            ('CLIENTNAME', 'C', 100, 0), ('BANK_MFO', 'N', 6, 0),
            ('BANK_NAME', 'C', 30, 0), ('BANK_ACCNO', 'C', 14, 0),
            ('TRACCIBAN', 'C', 29, 0), ('ACCOUNTNO', 'C', 14, 0),
            ('IBAN', 'C', 29, 0), ('SCHED_SUM', 'N', 19, 2),
            ('ISEXTACC', 'N', 1, 0), ('CODEZKP', 'N', 10, 0),
            ('COMMENTS', 'C', 180, 0), ('FLOWTYPE', 'C', 100, 0),
        ]
        sched_row = [{
            'SHED_DATE': fields.Date.context_today(self),
            'SCHED_NO': '1',
            'CLIENTNAME': self.company_id.name or '',
            'BANK_MFO': self._payer_mfo() or 0,
            'BANK_NAME': self.payer_account_id.bank_id.name or '',
            'BANK_ACCNO': '',
            'TRACCIBAN': transit,
            'ACCOUNTNO': '',
            'IBAN': debit,
            'SCHED_SUM': total,
            'ISEXTACC': 0,
            'CODEZKP': self.salary_project_code or 0,
            'COMMENTS': (self.payment_purpose or '').format(
                period=self._period_label(), employee='', rnokpp='')[:180],
            'FLOWTYPE': self.accrual_name or '',
        }]
        amt_fields = [
            ('IDCODE', 'C', 10, 0), ('ACCOUNTNO', 'C', 19, 0),
            ('SALACCIBAN', 'C', 29, 0), ('LASTNAME', 'C', 38, 0),
            ('FIRSTNAME', 'C', 38, 0), ('MIDDLENAME', 'C', 38, 0),
            ('AMOUNT', 'N', 19, 2),
        ]
        amt_rows = []
        for r in rows:
            last, first, middle = self._split_name(r['name'])
            amt_rows.append({
                'IDCODE': r['rnokpp'], 'ACCOUNTNO': '',
                'SALACCIBAN': r['account'], 'LASTNAME': last,
                'FIRSTNAME': first, 'MIDDLENAME': middle,
                'AMOUNT': r['amount'],
            })
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('ScheduleInfo.dbf', build_dbf(sched_fields, sched_row))
            zf.writestr('Amounts.dbf', build_dbf(amt_fields, amt_rows))
        return buf.getvalue()

    def _render_ibank2(self, rows):
        """iBank 2 UA — текстовий файл doc/pay_sheet (КЛЮЧ=значення), cp1251."""
        today = fields.Date.context_today(self)
        period = (self.date_to or today).strftime('%m,%Y')
        lines = [
            'Content-Type=doc/pay_sheet',
            'DATE_DOC=%s' % today.strftime('%d.%m.%Y'),
            'NUM_DOC=1',
            'CLN_OKPO=%s' % self._company_edrpou(),
            'PAYER_ACCOUNT=%s' % (
                self.payer_account_id.acc_number or '').replace(' ', ''),
            'ONFLOW_TYPE=%s' % (self.accrual_name or 'Заробітна плата'),
            'AMOUNT=',
            'VALUE_DATE=',
            'PERIOD=%s' % period,
        ]
        for i, r in enumerate(rows):
            lines += [
                'CARD_HOLDERS.%d.CARD_NUM=%s' % (i, r['account']),
                'CARD_HOLDERS.%d.CARD_HOLDER=%s' % (i, r['name']),
                'CARD_HOLDERS.%d.CARD_HOLDER_INN=%s' % (i, r['rnokpp']),
                'CARD_HOLDERS.%d.AMOUNT=%.2f' % (i, r['amount']),
            ]
        return ('\r\n'.join(lines) + '\r\n').encode('cp1251', 'replace')

    _FORMAT_REGISTRY = {
        'xml': ('_render_xml', 'xml'),
        'dbf': ('_render_dbf', 'dbf'),
        'ifobs': ('_render_ifobs', 'zip'),
        'ibank2': ('_render_ibank2', 'txt'),
    }

    def action_generate(self):
        self.ensure_one()
        slips = self._get_payslips()
        if not slips:
            raise UserError(_('Немає закритих (Done) листків за вибором.'))
        rows, _skipped = self._build_rows(slips)
        renderer, ext = self._FORMAT_REGISTRY.get(
            self.file_format, self._FORMAT_REGISTRY['xml'])
        if self.file_format in ('ifobs',) and not self.transit_account_id:
            raise UserError(_(
                'Для формату iFOBS вкажіть транзитний рахунок зарплатного '
                'проєкту.'))
        content = getattr(self, renderer)(rows)
        self.file_data = base64.b64encode(content)
        self.file_name = 'salary_%s_%s.%s' % (
            self.file_format, self._period_label().replace('.', '_') or 'export',
            ext)
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
