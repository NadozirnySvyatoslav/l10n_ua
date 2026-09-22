"""Tests for D5 (ESV) report — HR-28 from HR_UKRAINE.md.

Tests cover:
- Report creation
- Name computation
- State workflow (draft -> generated -> submitted)
- Computed totals
- Report line fields
- Unique constraint
- XML export of Додаток 1 (ЄСВ), #187
"""


from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReportD5(TransactionCase):
    """Test hr.report.d5 model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Петренко Олександр Миколайович',
            'company_id': cls.company.id,
        })

    def _create_report(self, **kwargs):
        vals = {
            'year': 2025,
            'month': '6',
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['hr.report.d5'].create(vals)

    def test_report_creation(self):
        """Report should be created in draft state."""
        report = self._create_report()
        self.assertEqual(report.state, 'draft')

    def test_report_name_computed(self):
        """Name should contain D5, year, and month."""
        report = self._create_report(year=2025, month='6')
        self.assertIn('Д5', report.name)
        self.assertIn('2025', report.name)

    def test_report_months(self):
        """All 12 months should be valid."""
        for m in [str(i) for i in range(1, 13)]:
            report = self._create_report(month=m)
            self.assertEqual(report.month, m)
            report.unlink()

    def test_report_generate(self):
        """Generate should move to generated state."""
        report = self._create_report()
        report.action_generate()
        self.assertEqual(report.state, 'generated')

    def test_report_submit(self):
        """Submit (симуляція успішної подачі) → submitted.

        action_submit тепер відкриває КЕП-підпис (l10n_ua.dps.submit.mixin);
        стан 'submitted' виставляє _dps_on_submitted за квитанцією. Повний
        КЕП-потік покрито тестами ЄРПН.
        """
        report = self._create_report()
        report.action_generate()
        report._dps_on_submitted('ok')
        self.assertEqual(report.state, 'submitted')

    def test_report_draft_reset(self):
        """Draft should reset from generated."""
        report = self._create_report()
        report.action_generate()
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_report_totals_empty(self):
        """Empty report should have zero totals."""
        report = self._create_report()
        self.assertEqual(report.total_employees, 0)
        self.assertEqual(report.total_esv_base, 0)
        self.assertEqual(report.total_esv, 0)

    def test_report_unique_constraint(self):
        """Same year + month + company should fail."""
        self._create_report(year=2030, month='11')
        with self.assertRaises(Exception):
            self._create_report(year=2030, month='11')

    def test_report_line_creation(self):
        """Should be able to add report lines."""
        report = self._create_report()
        self.env['hr.report.d5.line'].create({
            'report_id': report.id,
            'employee_id': self.employee.id,
            'rnokpp': '3184710691',
            'last_name': 'Петренко',
            'first_name': 'Олександр',
            'middle_name': 'Миколайович',
            'category': '1',
            'esv_base': 25000,
            'esv_amount': 5500,
        })
        self.assertEqual(len(report.line_ids), 1)

    def test_export_xml_requires_company_data(self):
        """Без реквізитів компанії експорт має чітко просити їх заповнити."""
        self.company.write({
            'edrpou': False, 'tax_office_code': False, 'director_id': False})
        report = self._create_report(year=2027, month='5')
        report.action_generate()
        with self.assertRaises(UserError):
            report.action_export_xml()

    def test_export_xml_draft_blocked(self):
        """У чернетці кнопка експорту має відмовити (спершу Generate)."""
        report = self._create_report(year=2027, month='7')
        with self.assertRaises(UserError):
            report.action_export_xml()

    def test_export_xml_produces_file(self):
        """Повний прохід: реквізити + рядок → xml_file збережено, це J0510210."""
        director = self.env['hr.employee'].create({
            'name': 'Директоренко Іван', 'company_id': self.company.id,
            'rnokpp': '2940910418'})
        self.company.write({
            'edrpou': '12345678', 'tax_office_code': '1716',
            'director_id': director.id})
        report = self._create_report(year=2027, month='9')
        report.action_generate()
        self.env['hr.report.d5.line'].create({
            'report_id': report.id, 'employee_id': self.employee.id,
            'rnokpp': '3184710691', 'last_name': 'Петренко',
            'first_name': 'Олександр', 'middle_name': 'Миколайович',
            'category': '1', 'esv_base': 25000, 'esv_amount': 5500})
        report.action_export_xml()
        self.assertTrue(report.xml_file)
        self.assertTrue(report.xml_filename.startswith('J0510210_2027_09'))
        xml = report.xml_file.content.decode('windows-1251')
        self.assertIn('<C_DOC>J05</C_DOC>', xml)
        self.assertIn('<T1RXXXXG6S ROWNUM="1">3184710691</T1RXXXXG6S>', xml)

    def test_report_line_categories(self):
        """Report line categories should be valid."""
        report = self._create_report(month='8')
        for cat in ['1', '2', '3', '4']:
            emp = self.env['hr.employee'].create({
                'name': f'Test Employee D5 Cat {cat}',
                'company_id': self.company.id,
            })
            self.env['hr.report.d5.line'].create({
                'report_id': report.id,
                'employee_id': emp.id,
                'rnokpp': f'318471069{cat}',
                'last_name': f'Test{cat}',
                'first_name': 'Test',
                'category': cat,
                'esv_base': 10000,
                'esv_amount': 2200,
            })
        self.assertEqual(len(report.line_ids), 4)
