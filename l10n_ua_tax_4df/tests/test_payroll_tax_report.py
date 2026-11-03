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


@tagged('post_install', '-at_install')
class TestPayrollTaxReportFop(TransactionCase):
    """ФОП-роботодавець: F0500111 за квартал, Д1 і Д4 на кожен місяць."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('hr_ua.validate_rnokpp', 'False')
        cls.company = cls.env.company
        office = cls.env['l10n_ua.tax.office'].create({'code': '2650', 'name': 'ГУ ДПС у м. Києві'})
        fop_form = cls.env['l10n_ua.legal.form'].search([('is_fop', '=', True)], limit=1)
        cls.company.write({
            'name': 'ФОП Бондаренко Марія Іванівна', 'l10n_ua_legal_form_id': fop_form.id,
            'company_registry': '3012345678', 'edrpou': False, 'tax_office_code': '2650',
            'l10n_ua_tax_office_id': office.id, 'katottg': 'UA80000000000093317',
            'zip': '01001', 'city': 'Київ', 'street': 'вул. Хрещатик, 1',
            'director_id': False,
        })
        cls.emp = cls.env['hr.employee'].create({
            'name': 'Коваль Ольга Петрівна', 'rnokpp': '2222222222', 'gender': 'female'})
        accrual_type = cls.env['hr.accrual.type'].search(
            [('category', '=', 'wage')], limit=1) or cls.env['hr.accrual.type'].create({
                'name': 'Тестова ЗП', 'code': 'TEST_WAGE_F', 'category': 'wage',
                'is_taxable_pdfo': True, 'is_military_tax': True, 'is_esv_base': True})
        # III квартал 2026: липень і серпень з нарахуваннями, вересень — порожній.
        for month, gross in ((7, 10000.0), (8, 12000.0)):
            slip = cls.env['hr.payslip'].create({
                'employee_id': cls.emp.id, 'company_id': cls.company.id,
                'date_from': date(2026, month, 1),
                'date_to': date(2026, month, 28),
                'accrual_ids': [(0, 0, {'accrual_type_id': accrual_type.id, 'amount': gross})],
            })
            slip.flush_recordset()
            cls.env.cr.execute(
                'UPDATE hr_payslip SET gross_salary=%s, net_salary=%s, pdfo_amount=%s, '
                'military_tax_amount=%s, esv_base=%s, esv_amount=%s, state=%s WHERE id=%s',
                (gross, gross * 0.77, gross * 0.18, gross * 0.05, gross, gross * 0.22,
                 'done', slip.id))
            slip.invalidate_recordset()

    def _report(self):
        rec = self.env['l10n_ua.payroll.tax.report'].create({'year': 2026, 'quarter': '3'})
        rec.action_calculate()
        return rec

    def _xml(self, data):
        return etree.fromstring(base64.b64decode(data))

    def test_quarter_sets_month_and_name(self):
        rec = self.env['l10n_ua.payroll.tax.report'].create({'year': 2026, 'quarter': '3'})
        self.assertTrue(rec.is_fop)
        self.assertEqual(rec.month, '9')
        self.assertIn('3 кв. 2026', rec.name)

    def test_calculate_per_month(self):
        rec = self._report()
        self.assertEqual(rec.month_ids.mapped('month_index'), [1, 2, 3])
        self.assertEqual(rec.month_ids.d5_report_id.mapped('month'), ['7', '8', '9'])
        self.assertEqual(sorted(rec.d4_line_ids.mapped('month_index')), [1, 2])
        self.assertEqual(rec.month_ids.mapped('income'), [10000.0, 12000.0, 0.0])
        self.assertAlmostEqual(rec.r01_income, 22000.0)

    def test_package_validates_against_official_xsd(self):
        rec = self._report()
        rec.action_generate_xml()
        _schema(os.path.join(SCHEMA_DIR, 'F0500111.xsd')).assertValid(self._xml(rec.xml_file))
        d1 = _schema(file_path('l10n_ua_hr_reports/tests/schemas/F0510111.xsd'))
        d4 = _schema(os.path.join(SCHEMA_DIR, 'F0510411.xsd'))
        rows = rec.month_ids.sorted('month_index')
        for row in rows[:2]:
            d1.assertValid(self._xml(row.d1_xml_file))
            d4.assertValid(self._xml(row.d4_xml_file))
        self.assertFalse(rows[2].d1_xml_file)
        self.assertFalse(rows[2].d4_xml_file)

    def test_main_form_month_columns(self):
        rec = self._report()
        rec.action_generate_xml()
        main = self._xml(rec.xml_file)
        head = main.find('DECLARHEAD')
        self.assertEqual(head.findtext('C_DOC'), 'F05')
        self.assertEqual(head.findtext('PERIOD_TYPE'), '2')
        self.assertEqual(head.findtext('PERIOD_MONTH'), '9')
        body = main.find('DECLARBODY')
        self.assertEqual(body.findtext('HZKV'), '3')
        self.assertEqual(body.findtext('R061G4'), '2')
        self.assertEqual(body.findtext('R064G4'), '2')
        self.assertEqual(body.findtext('R0101G3'), '10000.00')
        self.assertEqual(body.findtext('R0101G4'), '12000.00')
        self.assertIsNone(body.find('R0101G5'))
        self.assertEqual(body.findtext('R0107G4'), '2640.00')
        self.assertEqual(body.findtext('R091G3'), '1')
        # Підписує сам ФОП: його РНОКПП і ПІБ без «ФОП».
        self.assertEqual(body.findtext('HKBOS'), '3012345678')
        self.assertEqual(body.findtext('HBOS'), 'БОНДАРЕНКО МАРІЯ ІВАНІВНА')

    def test_linked_docs_distinguish_months(self):
        rec = self._report()
        rec.action_generate_xml()
        main = self._xml(rec.xml_file)
        docs = main.xpath('//LINKED_DOCS/DOC')
        self.assertEqual([d.findtext('C_DOC_SUB') for d in docs], ['101', '101', '104', '104'])
        self.assertEqual([d.findtext('C_DOC_CNT') for d in docs], ['1', '2', '1', '2'])
        files = [k for k in rec._attachment_files()]
        self.assertEqual([k for k, _d, _f in files], ['d1_1', 'd1_2', 'd4_1', 'd4_2'])
        names = [f.upper() for _k, _d, f in files]
        self.assertEqual(len(set(names)), 4)
        self.assertEqual([f.upper() for f in main.xpath('//LINKED_DOCS/DOC/FILENAME/text()')],
                         names)
        d1 = self._xml(rec.month_ids.sorted('month_index')[1].d1_xml_file)
        self.assertEqual(d1.findtext('DECLARBODY/HNM'), '2')
        self.assertEqual(d1.xpath('//T1RXXXXG101/text()'), ['8'])
