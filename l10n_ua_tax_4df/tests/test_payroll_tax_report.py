"""Податковий розрахунок ЮО (J0500111 v11): пакет головна форма + Д1 + Д4.

Схеми — офіційні XSD ДПС з оновлення СКЗ 1.34.9.0 (див. test_xsd_validation):
J0500111 і J0510411 лежать тут, J0510111 — у l10n_ua_hr_reports.
"""
import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'schemas')
CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'


def _schema(path):
    return etree.XMLSchema(etree.parse(path))


@tagged('post_install', '-at_install')
class TestPayrollTaxReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('hr_ua.validate_rnokpp', 'False')
        cls.company = cls.env.company
        cls.office = cls.env['l10n_ua.tax.office'].create({
            'code': '2650', 'name': 'ГУ ДПС у м. Києві'})
        cls.director = cls.env['hr.employee'].create({
            'name': 'Петренко Іван Іванович', 'rnokpp': '1111111111'})
        cls.company.write({
            'edrpou': '12345678', 'tax_office_code': '2650',
            'l10n_ua_tax_office_id': cls.office.id,
            'katottg': 'UA80000000000093317', 'zip': '01001', 'city': 'Київ',
            'street': 'вул. Хрещатик, 1', 'director_id': cls.director.id,
        })
        cls.emp1 = cls.env['hr.employee'].create({
            'name': 'Коваль Ольга Петрівна', 'rnokpp': '2222222222', 'gender': 'female'})
        cls.emp2 = cls.env['hr.employee'].create({
            'name': 'Шевчук Андрій Олегович', 'rnokpp': '3333333333', 'gender': 'male'})
        cls.accrual_type = cls.env['hr.accrual.type'].search(
            [('category', '=', 'wage')], limit=1) or cls.env['hr.accrual.type'].create({
                'name': 'Тестова ЗП', 'code': 'TEST_WAGE', 'category': 'wage',
                'is_taxable_pdfo': True, 'is_military_tax': True, 'is_esv_base': True})
        # Серпень 2026: перша — 20 000 грн, другий — 6 000 грн з доплатою бази
        # ЄСВ до мінімальної (8 647 грн).
        cls._slip(cls.emp1, 20000.0, 3600.0, 1000.0, 20000.0, 4400.0)
        cls._slip(cls.emp2, 6000.0, 1080.0, 300.0, 8647.0, 1902.34)

    @classmethod
    def _slip(cls, employee, gross, pdfo, military, esv_base, esv):
        slip = cls.env['hr.payslip'].create({
            'employee_id': employee.id, 'company_id': cls.company.id,
            'date_from': date(2026, 8, 1), 'date_to': date(2026, 8, 31),
            'accrual_ids': [(0, 0, {'accrual_type_id': cls.accrual_type.id, 'amount': gross})],
        })
        slip.flush_recordset()
        cls.env.cr.execute(
            'UPDATE hr_payslip SET gross_salary=%s, net_salary=%s, pdfo_amount=%s, '
            'military_tax_amount=%s, esv_base=%s, esv_amount=%s, state=%s WHERE id=%s',
            (gross, gross - pdfo - military, pdfo, military, esv_base, esv, 'done', slip.id))
        slip.invalidate_recordset()
        return slip

    def _report(self, **vals):
        return self.env['l10n_ua.payroll.tax.report'].create(
            {'year': 2026, 'month': '8', **vals})

    def _xml(self, rec, key=''):
        data = rec[f'{key}_xml_file' if key else 'xml_file']
        return etree.fromstring(base64.b64decode(data))

    # ------------------------------------------------------------------ розрахунок

    def test_calculate_collects_d1_and_d4(self):
        rec = self._report()
        rec.action_calculate()
        self.assertEqual(rec.state, 'calculated')
        self.assertEqual(len(rec.d5_report_id.line_ids), 2)
        self.assertEqual(len(rec.d4_line_ids), 2)
        self.assertAlmostEqual(rec.total_pdfo, 4680.0)
        self.assertAlmostEqual(rec.total_military, 1300.0)
        self.assertEqual(rec.headcount_avg, 2)

    def test_section1_matches_d1(self):
        """Рядок 3 = Σ гр. 20 Д1; доплата до мінімальної — окремо в 2.5/3.5."""
        rec = self._report()
        rec.action_calculate()
        self.assertAlmostEqual(rec.r01_income, 26000.0)
        self.assertAlmostEqual(rec.r011_salary, 26000.0)
        self.assertAlmostEqual(rec.r025_extra, 2647.0)
        self.assertAlmostEqual(rec.r021_base22, 26000.0)
        self.assertAlmostEqual(rec.r02_base, 28647.0)
        self.assertAlmostEqual(rec.r035_esv_extra, 582.34)
        self.assertAlmostEqual(rec.r03_esv, 4400.0 + 1902.34)
        self.assertAlmostEqual(rec.r031_esv22 + rec.r035_esv_extra, rec.r03_esv)
        self.assertEqual(rec.r092_count, 2)

    def test_reuses_existing_d5(self):
        d5 = self.env['hr.report.d5'].create({'year': 2026, 'month': '8'})
        rec = self._report()
        rec.action_calculate()
        self.assertEqual(rec.d5_report_id, d5)

    # ------------------------------------------------------------------ XML

    def test_package_validates_against_official_xsd(self):
        rec = self._report()
        rec.action_calculate()
        rec.action_generate_xml()
        _schema(os.path.join(SCHEMA_DIR, 'J0500111.xsd')).assertValid(self._xml(rec))
        _schema(file_path('l10n_ua_hr_reports/tests/schemas/J0510111.xsd')).assertValid(
            self._xml(rec, 'd1'))
        _schema(os.path.join(SCHEMA_DIR, 'J0510411.xsd')).assertValid(self._xml(rec, 'd4'))

    def test_linked_docs_point_to_real_filenames(self):
        """Головна форма перелічує файли додатків, а кожен додаток — головну."""
        rec = self._report()
        rec.action_calculate()
        rec.action_generate_xml()
        main = self._xml(rec)
        listed = [n.upper() for n in main.xpath('//LINKED_DOCS/DOC/FILENAME/text()')]
        self.assertEqual(listed, [rec.d1_xml_filename.upper(), rec.d4_xml_filename.upper()])
        self.assertEqual(main.xpath('//LINKED_DOCS/DOC/@TYPE'), ['1', '1'])
        for key in ('d1', 'd4'):
            annex = self._xml(rec, key)
            self.assertEqual(annex.xpath('//LINKED_DOCS/DOC/FILENAME/text()'),
                             [rec.xml_filename[:-4] + '.XML'])
            self.assertEqual(annex.xpath('//LINKED_DOCS/DOC/@TYPE'), ['2'])

    def test_main_form_rows(self):
        rec = self._report(number=2, headcount_avg=3)
        rec.action_calculate()
        rec.action_generate_xml()
        body = self._xml(rec).find('DECLARBODY')
        self.assertEqual(body.findtext('HNUM'), '2')
        self.assertEqual(body.findtext('HZM'), '8')
        self.assertEqual(body.findtext('R061G3'), '1')
        self.assertEqual(body.findtext('R064G3'), '1')
        self.assertEqual(body.findtext('R081G3'), '1')
        self.assertEqual(body.findtext('R091G3'), '3')
        self.assertEqual(body.findtext('R0101G3'), '26000.00')
        self.assertEqual(body.findtext('R01025G3'), '2647.00')
        self.assertEqual(body.findtext('R0103G3'), '6302.34')
        self.assertEqual(body.findtext('R0107G3'), '6302.34')
        self.assertIsNone(body.find('R01022G3'))
        d4 = self._xml(rec, 'd4').find('DECLARBODY')
        self.assertEqual(d4.findtext('HNUM'), '2')

    def test_missing_requisites_listed(self):
        rec = self._report()
        rec.action_calculate()
        self.company.katottg = False
        with self.assertRaisesRegex(UserError, 'КАТОТТГ'):
            rec.action_generate_xml()

    def test_no_payslips_refused(self):
        rec = self._report(month='3')
        rec.action_calculate()
        with self.assertRaisesRegex(UserError, 'розрахункових листів'):
            rec.action_generate_xml()

    # ------------------------------------------------------------------ подання

    def test_submit_sends_package_together(self):
        rec = self._report()
        rec.action_calculate()
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = rec.kep_prepare_signing()
        self.assertEqual([d['name'] for d in spec['documents']], ['doc', 'd1', 'd4'])
        posted = {}

        def fake_post(config, content, fname, headers, extra_files=()):
            posted['files'] = [fname] + [f for _c, f in extra_files]
            return [{'status': 'OK', 'id': n} for n in (1, 2, 3)]

        with patch(CONFIG + '._post_report', autospec=True, side_effect=fake_post):
            with self.assertRaisesRegex(UserError, 'D4'):
                rec.kep_submit_signed({'doc': 'E1', 'd1': 'E2'}, 'AUTH')
            rec.kep_submit_signed({'doc': 'E1', 'd1': 'E2', 'd4': 'E3'}, 'AUTH')
        self.assertEqual(posted['files'],
                         [rec.xml_filename, rec.d1_xml_filename, rec.d4_xml_filename])
        self.assertEqual(rec.state, 'submitted')
        self.assertEqual(rec.d5_report_id.state, 'submitted')
        with self.assertRaises(UserError):
            rec.action_calculate()
