"""Спільне читання XLS/XLSX (l10n_ua_bank_sync.tools.spreadsheet)."""

import io

from odoo.tests import BaseCase, tagged

from odoo.addons.l10n_ua_bank_sync.tools import spreadsheet

try:
    import xlwt
except ImportError:  # pragma: no cover
    xlwt = None
try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

ROWS = [
    ['Банк'],
    [],
    ['№', 'Дата', 'Сума', 'Призначення'],
    ['D1', '22.07.2026', -100.5, 'Оплата'],
    ['D2', '23.07.2026', 750.0, ''],
]


@tagged('post_install', '-at_install')
class TestSpreadsheetRows(BaseCase):

    def _xls(self):
        wb = xlwt.Workbook()
        sh = wb.add_sheet('Лист1')
        for r, row in enumerate(ROWS):
            for c, v in enumerate(row):
                sh.write(r, c, v)
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue()

    def _xlsx(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        for row in ROWS:
            ws.append(row)
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue()

    def test_is_xls(self):
        self.assertTrue(spreadsheet.is_xls(b'\xd0\xcf\x11\xe0' + b'\x00' * 8))
        self.assertFalse(spreadsheet.is_xls(b'PK\x03\x04'))
        self.assertFalse(spreadsheet.is_xls(b''))

    def test_read_xls_rows(self):
        if xlwt is None:
            self.skipTest('xlwt not installed')
        content = self._xls()
        self.assertTrue(spreadsheet.is_xls(content))
        rows = spreadsheet.read_xls_rows(content)
        self.assertEqual(len(rows), len(ROWS))
        self.assertEqual(rows[3][:4], ['D1', '22.07.2026', -100.5, 'Оплата'])
        # прямокутна таблиця: порожні клітинки — ''
        self.assertEqual(rows[1], [''] * len(rows[1]))

    def test_read_xlsx_rows(self):
        if openpyxl is None:
            self.skipTest('openpyxl not installed')
        content = self._xlsx()
        self.assertFalse(spreadsheet.is_xls(content))
        rows = spreadsheet.read_xlsx_rows(content)
        self.assertEqual(rows[3], ['D1', '22.07.2026', -100.5, 'Оплата'])
        # None → ''
        self.assertEqual(rows[4], ['D2', '23.07.2026', 750.0, ''])
        self.assertNotIn(None, [v for row in rows for v in row])
