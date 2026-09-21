"""Tests for ЄДЕБО XML import."""
import base64
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edebo>
  <students>
    <student>
      <last_name>Petrov</last_name>
      <first_name>Ivan</first_name>
      <middle_name>Sergeyovych</middle_name>
      <birthdate>2005-03-15</birthdate>
      <rnokpp>1234567890</rnokpp>
      <student_number>EDB-XML-001</student_number>
      <member_type>student</member_type>
    </student>
    <student>
      <last_name>Koval</last_name>
      <first_name>Mariya</first_name>
      <birthdate>2006-11-22</birthdate>
      <student_number>EDB-XML-002</student_number>
    </student>
  </students>
</edebo>
"""

# Alternative tag style (МОН variations)
ALT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<root>
  <person>
    <surname>Test</surname>
    <given_name>Pupil</given_name>
    <data_nar>2008-04-01</data_nar>
    <ipn>9876543210</ipn>
    <edebo_id>ALT-001</edebo_id>
  </person>
</root>
"""


@tagged('post_install', '-at_install', 'l10n_ua_education_edebo_xml')
class TestEdeboXml(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.year = cls.env['l10n_ua.education.academic.year'].create({
            'name': '2050/2051 EDEBO-XML',
            'year_start': 2050,
            'date_start': '2050-09-01',
            'date_end': '2051-06-30',
            'company_id': cls.env.company.id,
        })

    def test_xml_import_basic(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(SAMPLE_XML).decode(),
            'filename': 'edebo.xml',
            'file_format': 'custom',
            'dry_run': True,
        })
        wizard.action_import()
        self.assertIn('знайдено рядків: 2', wizard.result_log)

    def test_xml_alternative_tag_names(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(ALT_XML).decode(),
            'filename': 'alt.xml',
            'file_format': 'custom',
            'dry_run': True,
        })
        wizard.action_import()
        self.assertIn('знайдено рядків: 1', wizard.result_log)

    def test_xml_real_import_creates_members(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(SAMPLE_XML).decode(),
            'filename': 'edebo.xml',
            'file_format': 'custom',
            'dry_run': False,
            'default_member_state': 'enrolled',
        })
        wizard.action_import()
        member = self.env['l10n_ua.education.contingent.member'].search([
            ('student_number', '=', 'EDB-XML-001'),
        ])
        self.assertEqual(len(member), 1)
        self.assertEqual(member.state, 'enrolled')

    def test_invalid_xml_raises(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(b'not xml at all').decode(),
            'filename': 'bad.xml',
            'file_format': 'custom',
        })
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_empty_xml_raises(self):
        wizard = self.env['l10n_ua.edebo.import'].create({
            'academic_year_id': self.year.id,
            'file': base64.b64encode(b'<root></root>').decode(),
            'filename': 'empty.xml',
            'file_format': 'custom',
        })
        with self.assertRaises(UserError):
            wizard.action_import()
