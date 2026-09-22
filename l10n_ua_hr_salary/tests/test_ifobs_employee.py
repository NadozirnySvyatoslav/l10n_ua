"""Тести експорту даних працівників для карток iFOBS (#195)."""

import struct
from datetime import date

from .common import SalaryTestCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestIfobsEmployeeExport(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_str(
            'hr_ua.validate_rnokpp', 'False')
        cls.employee.write({
            'rnokpp': '1234567890',
            'passport_id': 'АА123456',
            'passport_issued_date': date(2015, 5, 20),
            'work_phone': '+380441112233',
            'birthday': date(1990, 3, 15),
        })

    def _wizard(self, employees):
        return self.env['hr.ifobs.employee.export'].create({
            'employee_ids': [(6, 0, employees.ids)],
        })

    def test_export_structure(self):
        wiz = self._wizard(self.employee)
        wiz.action_generate()
        self.assertEqual(wiz.state, 'done')
        self.assertTrue(wiz.file_name.endswith('.dbf'))
        b = wiz.file_data.content
        # dBASE III, 1 запис, 36 полів → header_len = 32 + 32*36 + 1.
        self.assertEqual(struct.unpack('<B', b[:1])[0], 0x03)
        self.assertEqual(struct.unpack('<I', b[4:8])[0], 1)
        self.assertEqual(struct.unpack('<H', b[8:10])[0], 32 + 32 * 36 + 1)

    def test_fio_and_inn_in_record(self):
        wiz = self._wizard(self.employee)
        wiz.action_generate()
        b = wiz.file_data.content
        hlen = struct.unpack('<H', b[8:10])[0]
        rec = b[hlen:]
        # прапорець(1) + BRANCHPART(N10) → FIO(C120) з позиції 11.
        fio = rec[11:11 + 120].decode('cp1251').strip()
        self.assertEqual(fio, self.employee.name)

    def test_missing_data_raises(self):
        self.employee.passport_id = False
        wiz = self._wizard(self.employee)
        with self.assertRaises(UserError):
            wiz.action_generate()

    def test_missing_phone_raises(self):
        self.employee.write({'work_phone': False, 'mobile_phone': False,
                             'private_phone': False})
        wiz = self._wizard(self.employee)
        with self.assertRaises(UserError):
            wiz.action_generate()
