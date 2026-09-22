"""Tests for ЄДЕБО import/export wizards."""
import base64
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_education_edebo')
class TestEdebo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.year = cls.env['l10n_ua.education.academic.year'].create({
            'name': '2031/2032 EDEBO',
            'year_start': 2031,
            'date_start': '2031-09-01',
            'date_end': '2032-06-30',
            'company_id': cls.env.company.id,
        })

    def test_csv_import_dry_run(self):
        csv_content = (
            "last_name,first_name,middle_name,birthdate,member_type,student_number,rnokpp\n"
            "Іваненко,Петро,Сергійович,2005-03-15,student,EDB-001,1234567890\n"
            "Коваль,Марія,Іванівна,2006-11-22,student,EDB-002,\n"
        )
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(csv_content.encode('utf-8')).decode(),
            'filename': 'edebo.csv',
            'file_format': 'csv',
            'dry_run': True,
        })
        wizard.action_import()
        self.assertIn('Перевірочний прогін', wizard.result_log)
        self.assertIn('знайдено рядків: 2', wizard.result_log)

    def test_csv_import_real(self):
        csv_content = (
            "last_name,first_name,middle_name,birthdate,member_type,student_number\n"
            "Тест,Студент,А,2005-01-01,student,REAL-001\n"
        )
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(csv_content.encode('utf-8')).decode(),
            'filename': 'edebo.csv',
            'file_format': 'csv',
            'dry_run': False,
            'default_member_state': 'enrolled',
        })
        wizard.action_import()
        members = self.env['l10n_ua.education.contingent.member'].search([
            ('student_number', '=', 'REAL-001'),
        ])
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].state, 'enrolled')
        self.assertEqual(members[0].partner_id.name, 'Тест Студент А')

    def test_bad_csv_raises(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(b"wrong,headers\nfoo,bar\n").decode(),
            'filename': 'bad.csv',
            'file_format': 'csv',
        })
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_custom_format_requires_plugin(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(b"any content").decode(),
            'filename': 'x.xml',
            'file_format': 'custom',
        })
        with self.assertRaises(UserError) as cm:
            wizard.action_import()
        self.assertIn('плагіну', cm.exception.args[0])

    def test_export_active_only(self):
        partner = self.env['res.partner'].create({'name': 'EXP Студент', 'is_company': False})
        member = self.env['l10n_ua.education.contingent.member'].create({
            'partner_id': partner.id, 'member_type': 'student',
            'academic_year_id': self.year.id, 'state': 'studying',
            'student_number': 'EXP-001',
        })
        wizard = self.env['l10n_ua.edebo.export'].create({
            'academic_year_id': self.year.id,
            'state_filter': 'active',
        })
        wizard.action_export()
        self.assertTrue(wizard.file)
        self.assertIn('edebo_export', wizard.filename)
        content = wizard.file.content.decode('utf-8')
        self.assertIn('EXP-001', content)
        # Name is split into last_name / first_name columns by the wizard
        self.assertIn('EXP', content)
        self.assertIn('Студент', content)

    def test_export_empty_raises(self):
        wizard = self.env['l10n_ua.edebo.export'].create({
            'academic_year_id': self.year.id,
            'state_filter': 'graduated',  # no graduated members → empty
        })
        with self.assertRaises(UserError):
            wizard.action_export()
