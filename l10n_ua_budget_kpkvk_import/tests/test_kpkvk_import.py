"""Tests for КПКВК bulk import wizard."""
import base64
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


CSV_CONTENT = b"""code,name,description
2201500,\xd0\x9d\xd0\xbe\xd0\xb2\xd0\xb0 \xd0\xbf\xd1\x80\xd0\xbe\xd0\xb3\xd1\x80\xd0\xb0\xd0\xbc\xd0\xb0,desc1
2201600,Test 2,
"""


@tagged('post_install', '-at_install', 'l10n_ua_budget_kpkvk_import')
class TestKpkvkImport(TransactionCase):

    def test_csv_import_creates(self):
        wizard = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2027,
            'file_format': 'csv',
            'file': base64.b64encode(CSV_CONTENT).decode(),
            'filename': 'kpkvk.csv',
        })
        wizard.action_import()
        rec = self.env['l10n_ua.kpkvk'].search([('code', '=', '2201500'), ('year', '=', 2027)])
        self.assertEqual(len(rec), 1)
        self.assertIn('Нова', rec.name)
        self.assertEqual(rec.description, 'desc1')

    def test_csv_skip_duplicates_without_overwrite(self):
        # First import
        wiz1 = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2028,
            'file_format': 'csv',
            'file': base64.b64encode(CSV_CONTENT).decode(),
            'filename': 'kpkvk.csv',
        })
        wiz1.action_import()
        # Second import without overwrite
        wiz2 = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2028,
            'file_format': 'csv',
            'file': base64.b64encode(CSV_CONTENT).decode(),
            'filename': 'kpkvk.csv',
            'overwrite': False,
        })
        wiz2.action_import()
        self.assertIn('пропущено: 2', wiz2.result_log)

    def test_csv_overwrite(self):
        wiz1 = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2029, 'file_format': 'csv',
            'file': base64.b64encode(CSV_CONTENT).decode(),
        })
        wiz1.action_import()
        new_content = b"code,name\n2201500,Updated Name\n"
        wiz2 = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2029, 'file_format': 'csv',
            'file': base64.b64encode(new_content).decode(),
            'overwrite': True,
        })
        wiz2.action_import()
        rec = self.env['l10n_ua.kpkvk'].search([('code', '=', '2201500'), ('year', '=', 2029)])
        self.assertEqual(rec.name, 'Updated Name')

    def test_bad_csv_raises(self):
        wizard = self.env['l10n_ua.kpkvk.import'].create({
            'year': 2030, 'file_format': 'csv',
            'file': base64.b64encode(b"wrong,headers\n").decode(),
        })
        with self.assertRaises(UserError):
            wizard.action_import()
