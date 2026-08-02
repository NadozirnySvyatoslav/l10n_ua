"""Тести експорту зарплатного файлу для клієнт-банку (#152)."""

import base64
import io
import struct
import zipfile
from datetime import date

from lxml import etree

from .common import SalaryTestCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestBankExport(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Вимкнути перевірку контрольної суми РНОКПП у тестах.
        cls.env['ir.config_parameter'].sudo().set_param(
            'hr_ua.validate_rnokpp', 'False')
        cls.employee.rnokpp = '1234567890'
        # The native bank_account_ids only accepts accounts held by the
        # employee's own work contact, which hr.employee.create provisions.
        cls.iban = 'UA213223130000026007233566001'
        cls.bank = cls.env['res.partner.bank'].create({
            'acc_number': cls.iban,
            'partner_id': cls.employee.work_contact_id.id,
        })
        cls.employee.bank_account_ids = [(4, cls.bank.id)]

    def _done_payslip(self):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        slip.action_compute_sheet()
        slip.write({'state': 'done'})
        return slip

    def _wizard(self, **kw):
        vals = {
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'payment_purpose': 'Заробітна плата за {period}',
        }
        vals.update(kw)
        return self.env['hr.payslip.bank.export'].create(vals)

    def test_xml_export(self):
        slip = self._done_payslip()
        wiz = self._wizard(file_format='xml')
        wiz.action_generate()
        self.assertEqual(wiz.state, 'done')
        self.assertTrue(wiz.file_name.endswith('.xml'))
        content = base64.b64decode(wiz.file_data)
        root = etree.fromstring(content)
        self.assertEqual(root.tag, 'PaymentPackage')
        payments = root.findall('Payment')
        self.assertEqual(len(payments), 1)
        p = payments[0]
        self.assertEqual(p.findtext('Rnokpp'), '1234567890')
        self.assertEqual(p.findtext('Account'), self.iban)
        self.assertEqual(p.findtext('Amount'), f'{slip.net_salary:.2f}')
        self.assertEqual(p.findtext('Purpose'), 'Заробітна плата за 06.2025')
        self.assertEqual(root.get('count'), '1')

    def test_dbf_export(self):
        slip = self._done_payslip()
        wiz = self._wizard(file_format='dbf')
        wiz.action_generate()
        self.assertTrue(wiz.file_name.endswith('.dbf'))
        b = base64.b64decode(wiz.file_data)
        version, = struct.unpack('<B', b[:1])
        nrec, = struct.unpack('<I', b[4:8])
        hlen, = struct.unpack('<H', b[8:10])
        self.assertEqual(version, 0x03)
        self.assertEqual(nrec, 1)
        # Перший запис: прапорець(1) + NN(5) + OKPO(10) → OKPO у 6..16.
        rec = b[hlen:]
        okpo = rec[6:16].decode('cp1251').strip()
        self.assertEqual(okpo, '1234567890')

    def test_missing_account_raises(self):
        self._done_payslip()
        self.employee.bank_account_ids = [(5, 0, 0)]
        wiz = self._wizard(file_format='xml')
        with self.assertRaises(UserError):
            wiz.action_generate()

    def test_no_done_payslip_raises(self):
        # Листок у чернетці — не потрапляє у вибірку.
        self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        wiz = self._wizard(file_format='xml')
        with self.assertRaises(UserError):
            wiz.action_generate()

    # --- #197: банк-специфічні формати iFOBS / iBank 2 UA ---

    def test_ifobs_export(self):
        slip = self._done_payslip()
        transit = self.env['res.partner.bank'].create({
            'acc_number': '26005678901234',
            'partner_id': self.bank.partner_id.id,
        })
        wiz = self._wizard(file_format='ifobs')
        wiz.transit_account_id = transit.id
        wiz.salary_project_code = '12345'
        wiz.action_generate()
        self.assertTrue(wiz.file_name.endswith('.zip'))
        zf = zipfile.ZipFile(io.BytesIO(base64.b64decode(wiz.file_data)))
        self.assertEqual(set(zf.namelist()), {'ScheduleInfo.dbf', 'Amounts.dbf'})
        # ScheduleInfo — рівно 1 запис.
        sched = zf.read('ScheduleInfo.dbf')
        self.assertEqual(struct.unpack('<I', sched[4:8])[0], 1)
        # Amounts — 1 запис (1 працівник), РНОКПП у першому полі (після прапорця).
        amt = zf.read('Amounts.dbf')
        self.assertEqual(struct.unpack('<I', amt[4:8])[0], 1)
        hlen = struct.unpack('<H', amt[8:10])[0]
        idcode = amt[hlen + 1:hlen + 11].decode('cp1251').strip()
        self.assertEqual(idcode, '1234567890')

    def test_ifobs_requires_transit(self):
        self._done_payslip()
        wiz = self._wizard(file_format='ifobs')
        wiz.transit_account_id = False
        with self.assertRaises(UserError):
            wiz.action_generate()

    def test_ibank2_export(self):
        slip = self._done_payslip()
        wiz = self._wizard(file_format='ibank2')
        wiz.accrual_name = 'Заробітна плата'
        wiz.action_generate()
        self.assertTrue(wiz.file_name.endswith('.txt'))
        text = base64.b64decode(wiz.file_data).decode('cp1251')
        self.assertIn('Content-Type=doc/pay_sheet', text)
        self.assertIn('ONFLOW_TYPE=Заробітна плата', text)
        self.assertIn('CARD_HOLDERS.0.CARD_NUM=%s' % self.iban, text)
        self.assertIn('CARD_HOLDERS.0.CARD_HOLDER_INN=1234567890', text)
        self.assertIn('CARD_HOLDERS.0.AMOUNT=%.2f' % slip.net_salary, text)
        self.assertIn('PERIOD=06,2025', text)

    # --- Ukrainian IBAN carried onto the native bank_account_ids ---

    def test_primary_account_used_for_export(self):
        """With several accounts the export must pay the primary one."""
        second = self.env['res.partner.bank'].create({
            'acc_number': 'UA913223130000026007233566002',
            'partner_id': self.employee.work_contact_id.id,
        })
        self.employee.bank_account_ids = [(4, second.id)]
        self.assertEqual(len(self.employee.bank_account_ids), 2)
        expected = self.employee.primary_bank_account_id
        self.assertTrue(expected)
        self._done_payslip()
        wiz = self._wizard(file_format='xml')
        wiz.action_generate()
        root = etree.fromstring(base64.b64decode(wiz.file_data))
        payments = root.findall('Payment')
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].findtext('Account'), expected.acc_number)

    def test_iban_written_without_spaces(self):
        """A grouped IBAN reaches the bank file as 29 contiguous characters."""
        self.bank.acc_number = 'UA21 3223 1300 0002 6007 2335 6600 1'
        self._done_payslip()
        wiz = self._wizard(file_format='xml')
        wiz.action_generate()
        root = etree.fromstring(base64.b64decode(wiz.file_data))
        account = root.findall('Payment')[0].findtext('Account')
        self.assertEqual(account, self.iban)
        self.assertEqual(len(account), 29)

    def test_ua_iban_fits_dbf_field_width(self):
        """A 29-char IBAN must survive the fixed-width DBF fields untruncated.

        build_dbf pads or slices silently, so a field declared too narrow
        would ship a mangled account number with no error at all.
        """
        self._done_payslip()
        transit = self.env['res.partner.bank'].create({
            'acc_number': 'UA983053990000026007233566003',
            'partner_id': self.bank.partner_id.id,
        })
        wiz = self._wizard(file_format='ifobs')
        wiz.transit_account_id = transit.id
        wiz.salary_project_code = '12345'
        wiz.action_generate()
        # DBF is binary, so the account is looked for as encoded bytes.
        encoded_iban = self.iban.encode('cp1251')
        zf = zipfile.ZipFile(io.BytesIO(base64.b64decode(wiz.file_data)))
        self.assertIn(encoded_iban, zf.read('Amounts.dbf'))

        wiz_dbf = self._wizard(file_format='dbf')
        wiz_dbf.action_generate()
        self.assertIn(encoded_iban, base64.b64decode(wiz_dbf.file_data))

    def test_run_defaults_period(self):
        run = self.env['hr.payslip.run'].create({
            'name': 'Червень 2025',
            'date_start': date(2025, 6, 1),
            'date_end': date(2025, 6, 30),
        })
        slip = self._done_payslip()
        slip.payslip_run_id = run.id
        wiz = self.env['hr.payslip.bank.export'].create({
            'payslip_run_id': run.id, 'file_format': 'xml'})
        wiz.action_generate()
        root = etree.fromstring(base64.b64decode(wiz.file_data))
        self.assertEqual(len(root.findall('Payment')), 1)
