"""Електронний 1-ПВ (#458): XML S0301016 / S0301121 і подання.

Схеми — з повного пакета СКЗ ДПС 1.34.0.0 (tests/schemas). Фікстура: одна
штатна працівниця з окладом 20 000 грн щомісяця 2026 року.
"""
import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'schemas')
CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'


@tagged('post_install', '-at_install', 'l10n_ua_hr_reports')
class TestReportLaborXml(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.director = cls.env['hr.employee'].create({'name': 'Петренко Іван Іванович'})
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ «Праця»',
            'currency_id': cls.env.ref('base.UAH').id,
            'edrpou': '12345678',
            'katottg': 'UA32120110050099925',
            'kved_main': '62.01',
            'zip': '08100', 'city': 'Вишневе', 'street': 'вул. Київська, 1',
            'phone': '0441234567', 'email': 'hr@example.com',
        })
        if 'director_id' in cls.company._fields:
            cls.company.director_id = cls.director
        employee = cls.env['hr.employee'].create({
            'name': 'Олена Коваль', 'company_id': cls.company.id, 'gender': 'female'})
        employee.with_context(active_test=False).version_ids[:1].write({
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'work_rate': 1.0,
        })
        salary = cls.env.ref('l10n_ua_hr_salary.accrual_type_salary')
        for month in (1, 2, 3):
            slip = cls.env['hr.payslip'].create({
                'employee_id': employee.id, 'company_id': cls.company.id,
                'date_from': date(2026, month, 1),
                'date_to': date(2026, month, 28),
            })
            cls.env['hr.payslip.accrual'].create({
                'payslip_id': slip.id, 'accrual_type_id': salary.id,
                'quantity': 1, 'rate': 20000, 'amount': 20000,
            })
            slip.write({'worked_hours': 160, 'overtime_hours': 0.0, 'state': 'done'})

    def _report(self, **vals):
        report = self.env['hr.report.labor'].create(
            {'company_id': self.company.id, 'year': 2026, **vals})
        report.action_compute()
        return report

    def _xml(self, report):
        report.action_export_xml()
        return etree.fromstring(base64.b64decode(report.xml_file))

    def _assert_valid(self, report, schema):
        xsd = etree.XMLSchema(etree.parse(os.path.join(SCHEMA_DIR, schema)))
        xsd.assertValid(self._xml(report))

    # ------------------------------------------------------------------ місячна

    def test_monthly_validates(self):
        self._assert_valid(self._report(period_type='month', month='1'), 'S0301016.xsd')

    def test_monthly_header_and_values(self):
        report = self._report(period_type='month', month='2')
        root = self._xml(report)
        head, body = root.find('DECLARHEAD'), root.find('DECLARBODY')
        self.assertEqual(head.findtext('C_DOC') + head.findtext('C_DOC_SUB')
                         + head.findtext('C_DOC_VER'), 'S0301016')
        # Київська область (32), район 12 — з КАТОТТГ компанії.
        self.assertEqual(head.findtext('C_REG'), '32')
        self.assertEqual(head.findtext('C_RAJ'), '012')
        self.assertEqual(head.findtext('PERIOD_TYPE'), '1')
        self.assertEqual(head.findtext('PERIOD_MONTH'), '2')
        self.assertEqual(body.findtext('A1020'), '%.1f' % report.get_value('1020'))
        self.assertEqual(body.findtext('A1040'), '%d' % report.get_value('1040'))
        self.assertEqual(body.findtext('KATOTTG_FACT'), '32120110050099925')
        self.assertEqual(body.findtext('FIRM_EDRPOU'), '12345678')
        # 32 012 0012345678 S03 010 16 1 00 00001 02 2026 — 37 знаків.
        self.assertEqual(report.xml_filename, '320120012345678S030101610000001022026.xml')

    def test_recompute_drops_stale_xml(self):
        report = self._report(period_type='month', month='1')
        report.action_export_xml()
        self.assertTrue(report.xml_file)
        report.action_compute()
        self.assertFalse(report.xml_file)

    # --------------------------------------------------------------- квартальна

    def test_quarterly_validates(self):
        report = self._report(period_type='quarter', quarter='1')
        self._assert_valid(report, 'S0301121.xsd')
        root = self._xml(report)
        head, body = root.find('DECLARHEAD'), root.find('DECLARBODY')
        self.assertEqual(head.findtext('PERIOD_TYPE'), '2')
        self.assertEqual(head.findtext('PERIOD_MONTH'), '3')
        self.assertEqual(body.findtext('A3070_1'), '%d' % report.get_value('3070', '1'))
        self.assertEqual(body.findtext('A5010'), '%.1f' % report.get_value('5010'))
        # Рядки лише IV кварталу в I кварталі не пишуться.
        self.assertIsNone(body.find('A8010'))

    def test_fourth_quarter_validates(self):
        report = self._report(period_type='quarter', quarter='4')
        report._line('8030').write({'is_manual': True, 'manual_value': 8647})
        self._assert_valid(report, 'S0301121.xsd')
        body = self._xml(report).find('DECLARBODY')
        self.assertEqual(body.findtext('A8030'), '8647.00')
        self.assertIsNotNone(body.find('A3100_1'))

    # ---------------------------------------------------------------- реквізити

    def test_city_with_special_status_needs_district(self):
        self.company.katottg = 'UA80000000000093317'
        report = self._report(period_type='month', month='1')
        with self.assertRaisesRegex(UserError, 'код району'):
            report.action_export_xml()
        self.company.l10n_ua_stat_district_code = '7'
        head = self._xml(report).find('DECLARHEAD')
        self.assertEqual((head.findtext('C_REG'), head.findtext('C_RAJ')), ('80', '007'))

    def test_district_code_digits_only(self):
        with self.assertRaises(ValidationError):
            self.company.l10n_ua_stat_district_code = 'А1'

    def test_missing_katottg(self):
        self.company.katottg = False
        report = self._report(period_type='month', month='1')
        with self.assertRaisesRegex(UserError, 'КАТОТТГ'):
            report.action_export_xml()

    def test_before_2025_refused(self):
        report = self.env['hr.report.labor'].create({
            'company_id': self.company.id, 'year': 2024,
            'period_type': 'month', 'month': '12'})
        report.action_compute()
        with self.assertRaisesRegex(UserError, '2025'):
            report.action_export_xml()

    # ------------------------------------------------------------------ подання

    def test_submit(self):
        report = self._report(period_type='month', month='3')
        self.env['l10n_ua.tax.cabinet.config'].create({
            'name': 'Кабінет', 'taxpayer_code': '12345678',
            'company_id': self.company.id, 'active': True})
        with self.assertRaisesRegex(UserError, 'виконаним'):
            report.kep_prepare_signing()
        report.action_done()
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = report.kep_prepare_signing()
        doc = spec['documents'][0]
        self.assertEqual(doc['filename'], report.xml_filename)
        self.assertEqual(base64.b64decode(doc['data_b64'])[:43],
                         b'<?xml version="1.0" encoding="windows-1251"')
        with patch(CONFIG + '._api_submit_document_presigned',
                   return_value=[{'status': 'OK', 'message': 'Прийнято'}]) as post:
            report.kep_submit_signed({'doc': 'SIGNED'}, 'AUTH')
        self.assertEqual(post.call_args.args[1], report.xml_filename)
        self.assertTrue(report.submission_date)
        with self.assertRaises(UserError):
            report.action_draft()
