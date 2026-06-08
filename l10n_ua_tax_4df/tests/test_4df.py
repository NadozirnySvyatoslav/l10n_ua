"""Тести 4ДФ — об'єднана звітність ПДФО/ВЗ/ЄСВ."""

import base64
from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestReport4DF(TransactionCase):
    """Тести квартального звіту 4ДФ."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Disable RNOKPP checksum validation for tests
        cls.env['ir.config_parameter'].sudo().set_param(
            'hr_ua.validate_rnokpp', 'False')
        cls.emp1 = cls.env['hr.employee'].create({
            'name': 'Тестова Іванна',
            'company_id': cls.company.id,
            'rnokpp': '1234567890',
        })
        cls.emp2 = cls.env['hr.employee'].create({
            'name': 'Тестовий Петро',
            'company_id': cls.company.id,
            'rnokpp': '0987654321',
        })
        cls.accrual_type = cls.env['hr.accrual.type'].search(
            [('category', '=', 'wage')], limit=1
        ) or cls.env['hr.accrual.type'].create({
            'name': 'Тестова ЗП',
            'code': 'TEST_WAGE',
            'category': 'wage',
            'is_taxable_pdfo': True,
            'is_military_tax': True,
            'is_esv_base': True,
        })

    def _create_payslip(self, employee, date_from, date_to, gross, pdfo, military,
                       esv_base, esv, net=None):
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'accrual_ids': [(0, 0, {
                'accrual_type_id': self.accrual_type.id,
                'amount': gross,
            })],
        })
        # Trigger compute, then override stored values directly to control
        # test assertions deterministically (avoid drift from tax-rate logic).
        slip.flush_recordset()
        self.env.cr.execute(
            'UPDATE hr_payslip SET gross_salary=%s, net_salary=%s, '
            'pdfo_amount=%s, military_tax_amount=%s, esv_base=%s, '
            'esv_amount=%s, state=%s WHERE id=%s',
            (gross, net if net is not None else (gross - pdfo - military),
             pdfo, military, esv_base, esv, 'done', slip.id),
        )
        slip.invalidate_recordset()
        return slip

    def test_creation_and_name(self):
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025,
            'quarter': '1',
        })
        self.assertEqual(rec.name, '4ДФ 2025 Q1')
        self.assertEqual(rec.state, 'draft')

    def test_unique_period_company(self):
        self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        with self.assertRaises(Exception):
            self.env['l10n_ua.tax.4df'].create({
                'year': 2025, 'quarter': '1',
            })

    def test_quarter_dates(self):
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        date_from, date_to = rec._get_quarter_dates()
        self.assertEqual(date_from, date(2025, 1, 1))
        self.assertEqual(date_to, date(2025, 3, 31))

        rec.quarter = '4'
        date_from, date_to = rec._get_quarter_dates()
        self.assertEqual(date_from, date(2025, 10, 1))
        self.assertEqual(date_to, date(2025, 12, 31))

    def test_generate_aggregates_per_employee(self):
        # Два payslips для emp1 у Q1
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        self._create_payslip(self.emp1, date(2025, 2, 1), date(2025, 2, 28),
                            gross=12000, pdfo=2160, military=600,
                            esv_base=12000, esv=2640)
        # Один для emp2
        self._create_payslip(self.emp2, date(2025, 3, 1), date(2025, 3, 31),
                            gross=15000, pdfo=2700, military=750,
                            esv_base=15000, esv=3300)

        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        self.assertEqual(rec.state, 'generated')
        # Appendix 4DF — 2 рядки (по працівнику)
        self.assertEqual(len(rec.line_4df_ids), 2)
        emp1_line = rec.line_4df_ids.filtered(lambda l: l.employee_id == self.emp1)
        self.assertAlmostEqual(emp1_line.accrued_amount, 22000, places=2)
        self.assertAlmostEqual(emp1_line.pdfo_amount, 3960, places=2)
        self.assertAlmostEqual(emp1_line.military_amount, 1100, places=2)
        emp2_line = rec.line_4df_ids.filtered(lambda l: l.employee_id == self.emp2)
        self.assertAlmostEqual(emp2_line.accrued_amount, 15000, places=2)

        # Appendix 1 — теж 2 рядки
        self.assertEqual(len(rec.line_t1_ids), 2)
        emp1_t1 = rec.line_t1_ids.filtered(lambda l: l.employee_id == self.emp1)
        self.assertAlmostEqual(emp1_t1.esv_base, 22000, places=2)
        self.assertAlmostEqual(emp1_t1.esv_amount, 4840, places=2)
        # emp1 — 2 місяці (Jan + Feb)
        self.assertEqual(emp1_t1.months_count, 2)

    def test_totals_computed(self):
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        self._create_payslip(self.emp2, date(2025, 1, 1), date(2025, 1, 31),
                            gross=15000, pdfo=2700, military=750,
                            esv_base=15000, esv=3300)
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        self.assertEqual(rec.total_employees, 2)
        self.assertAlmostEqual(rec.total_accrued, 25000, places=2)
        self.assertAlmostEqual(rec.total_pdfo, 4500, places=2)
        self.assertAlmostEqual(rec.total_military, 1250, places=2)
        self.assertAlmostEqual(rec.total_esv, 5500, places=2)

    def test_xml_export(self):
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        rec.action_generate_xml()
        self.assertTrue(rec.xml_file)
        self.assertTrue(rec.xml_filename.startswith('J0501T01'))
        xml = base64.b64decode(rec.xml_file).decode('utf-8')
        self.assertIn('<DECLAR', xml)
        self.assertIn('<RNOKPP>1234567890</RNOKPP>', xml)
        self.assertIn('<PDFO>1800.00</PDFO>', xml)

    def test_submit_workflow(self):
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        rec.action_submit()
        self.assertEqual(rec.state, 'submitted')
        self.assertTrue(rec.submission_date)

    def test_cannot_submit_from_draft(self):
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        with self.assertRaises(UserError):
            rec.action_submit()

    def test_draft_resets_submission_date(self):
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        rec.action_submit()
        rec.action_draft()
        self.assertEqual(rec.state, 'draft')
        self.assertFalse(rec.submission_date)

    def test_regenerate_blocked_after_submission(self):
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        rec.action_submit()
        with self.assertRaises(UserError):
            rec.action_generate()

    def test_form_code_default(self):
        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        self.assertEqual(rec.form_code, 'J0501T01')

    def test_other_quarter_payslips_excluded(self):
        """Payslip за межами кварталу не потрапляє в звіт."""
        # Q1 payslip
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        # Q2 payslip
        self._create_payslip(self.emp1, date(2025, 4, 1), date(2025, 4, 30),
                            gross=20000, pdfo=3600, military=1000,
                            esv_base=20000, esv=4400)
        rec_q1 = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec_q1.action_generate()
        self.assertAlmostEqual(rec_q1.total_accrued, 10000, places=2)
        self.assertEqual(len(rec_q1.line_4df_ids), 1)

    def test_draft_payslips_excluded(self):
        """Payslip у стані draft не потрапляє в звіт."""
        self._create_payslip(self.emp1, date(2025, 1, 1), date(2025, 1, 31),
                            gross=10000, pdfo=1800, military=500,
                            esv_base=10000, esv=2200)
        # Draft payslip — не повинен потрапити
        slip = self._create_payslip(self.emp1, date(2025, 2, 1), date(2025, 2, 28),
                            gross=20000, pdfo=3600, military=1000,
                            esv_base=20000, esv=4400)
        slip.state = 'draft'

        rec = self.env['l10n_ua.tax.4df'].create({
            'year': 2025, 'quarter': '1',
        })
        rec.action_generate()
        # Тільки перший payslip
        emp1_line = rec.line_4df_ids
        self.assertEqual(len(emp1_line), 1)
        self.assertAlmostEqual(emp1_line.accrued_amount, 10000, places=2)
