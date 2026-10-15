"""Повідомлення ДПС про прийняття працівника на роботу (#369).

Постанова КМУ № 413 (ред. від 21.01.2026), форма — додаток 1 у ред.
постанови КМУ № 184 від 21.02.2025; електронна форма J3001005/F3001005.
"""

import base64
import os
from datetime import date, timedelta

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schemas', 'J3001005.xsd')


@tagged('post_install', '-at_install', 'l10n_ua_hr_reports')
class TestHireNotice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ Тест Найм',
            'edrpou': '12345678',
            'tax_office_code': '2650',
        })
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.director = cls.env['hr.employee'].create({
            'name': 'Олександр ПЕТРЕНКО',
            'company_id': cls.company.id,
            'rnokpp': '1234567899',
        })
        cls.company.director_id = cls.director
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Коваль Ірина Петрівна',
            'company_id': cls.company.id,
            'rnokpp': '3184710691',
        })
        cls.Notice = cls.env['hr.hire.notice']

    def _hire(self, employee=None, start=None, form='main', order_date=None):
        start = start or date(2026, 3, 2)
        return self.env['hr.order'].create({
            'order_type': 'hiring',
            'employee_id': (employee or self.employee).id,
            'date': order_date or start - timedelta(days=3),
            'date_start': start,
            'employment_form': form,
            'company_id': self.company.id,
        })

    def _xml(self, notice):
        notice.action_generate_xml()
        raw = base64.b64decode(notice.xml_file)
        return etree.fromstring(raw)

    @staticmethod
    def _text(doc, tag):
        node = doc.find('.//%s' % tag)
        return node.text if node is not None else None

    # --- XML з наказу -------------------------------------------------

    def test_xml_from_hiring_order(self):
        order = self._hire()
        order.action_confirm()
        notice = self.Notice.create_from_order(order)
        self.assertEqual(notice.person_category, '1')
        self.assertEqual(notice.order_number, order.name)
        self.assertTrue(notice.is_mandatory)

        doc = self._xml(notice)
        self.assertEqual(notice.state, 'generated')
        head = doc.find('DECLARHEAD')
        self.assertEqual(self._text(head, 'TIN'), '12345678')
        self.assertEqual(self._text(head, 'C_DOC'), 'J30')
        self.assertEqual(self._text(head, 'C_DOC_SUB'), '010')
        self.assertEqual(self._text(head, 'C_DOC_VER'), '5')
        self.assertEqual(self._text(head, 'C_REG'), '26')
        self.assertEqual(self._text(head, 'C_RAJ'), '50')
        self.assertEqual(self._text(head, 'C_STI_ORIG'), '2650')
        body = doc.find('DECLARBODY')
        self.assertEqual(self._text(body, 'HPOCH'), '1')
        self.assertIsNone(body.find('HSKAS'))
        self.assertEqual(self._text(body, 'HTIN'), '12345678')
        self.assertEqual(self._text(body, 'HNAME'), 'ТОВ Тест Найм')
        self.assertEqual(self._text(body, 'T1RXXXXG5'), '1')
        self.assertEqual(self._text(body, 'T1RXXXXG6S'), '3184710691')
        self.assertEqual(self._text(body, 'T1RXXXXG8S'), 'Коваль Ірина Петрівна')
        self.assertEqual(self._text(body, 'T1RXXXXG9'), '1')
        self.assertEqual(self._text(body, 'T1RXXXXG10S'), order.name)
        self.assertEqual(self._text(body, 'T1RXXXXG11D'), '27022026')
        self.assertEqual(self._text(body, 'T1RXXXXG12D'), '02032026')
        self.assertEqual(self._text(body, 'HKBOS'), '1234567899')
        self.assertEqual(self._text(body, 'HBOS'), 'Олександр ПЕТРЕНКО')
        # Ім'я файлу за правилом ДПС: C_REG C_RAJ TIN(10) C_DOC SUB VER ...
        self.assertTrue(notice.xml_filename.startswith('26500012345678J3001005'))
        self.assertTrue(notice.xml_filename.endswith('2650.xml'))
        self.assertEqual(len(notice.xml_filename), len('2650' '0012345678' 'J30010' '05'
                                                        '1' '00' '0000001' '1' '01' '2026'
                                                        '2650' '.xml'))

    def test_create_from_order_is_idempotent(self):
        order = self._hire()
        first = self.Notice.create_from_order(order)
        self.assertEqual(self.Notice.create_from_order(order), first)
        self.assertEqual(order.hire_notice_count, 1)

    def test_secondary_employment_category_2(self):
        notice = self.Notice.create_from_order(self._hire(form='secondary'))
        self.assertEqual(notice.person_category, '2')

    def test_foreigner_citizenship(self):
        self.employee.country_id = self.env.ref('base.pl')
        notice = self.Notice.create_from_order(self._hire())
        self.assertEqual(notice.citizenship, '0')
        self.assertEqual(self._text(self._xml(notice), 'T1RXXXXG9'), '0')

    def test_cancelling_notice(self):
        notice = self.Notice.create_from_order(self._hire())
        notice.action_generate_xml()
        notice.action_mark_sent()
        action = notice.action_create_cancelling()
        cancel = self.Notice.browse(action['res_id'])
        body = self._xml(cancel).find('DECLARBODY')
        self.assertEqual(self._text(body, 'HSKAS'), '1')
        self.assertIsNone(body.find('HPOCH'))
        self.assertNotEqual(cancel.doc_cnt, notice.doc_cnt)

    def test_missing_company_data_raises(self):
        self.company.tax_office_code = False
        notice = self.Notice.create_from_order(self._hire())
        with self.assertRaises(UserError):
            notice.action_generate_xml()

    # --- ЦПД / гіг / виключення ----------------------------------------

    def test_gig_contract_from_version(self):
        order = self._hire()
        version = self.Notice._order_version(order)
        self.assertTrue(version)
        version.sudo().contract_type_ua = 'gig'
        notice = self.Notice.create_from_version(version)
        self.assertEqual(notice.person_category, '3')
        self.assertTrue(notice.is_mandatory)
        self.assertFalse(notice.order_number)
        body = self._xml(notice).find('DECLARBODY')
        self.assertEqual(self._text(body, 'T1RXXXXG5'), '3')
        # Гр. 10 не заповнюється для гіг-контракту.
        self.assertIsNone(body.find('T1RXXXXG10S'))
        self.assertEqual(self._text(body, 'T1RXXXXG11D'), '02032026')

    def test_civil_contract_not_mandatory(self):
        order = self._hire(start=date.today() + timedelta(days=1))
        self.Notice._order_version(order).sudo().contract_type_ua = 'civil'
        notice = self.Notice.create_from_order(order)
        self.assertEqual(notice.person_category, '4')
        self.assertFalse(notice.is_mandatory)
        self.assertFalse(self.Notice._hiring_orders_without_notice(
            date.today() + timedelta(days=3)) & order)

    def test_director_excluded(self):
        order = self._hire(employee=self.director)
        with self.assertRaises(UserError):
            self.Notice.create_from_order(order)
        self.assertFalse(order.hire_notice_missing)
        self.assertFalse(self.Notice._hiring_orders_without_notice(
            date(2026, 12, 31)) & order)

    # --- контроль строку -----------------------------------------------

    def test_deadline_reminder_activity(self):
        today = date.today()
        order = self._hire(start=today + timedelta(days=1))
        self.assertTrue(order.hire_notice_missing)
        self.Notice._cron_check_hire_notice_deadlines()
        summaries = self.Notice._reminder_summaries()
        acts = order.activity_ids.filtered(lambda a: a.summary in summaries)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts.date_deadline, today)
        # Повторний прогін не дублює нагадування.
        self.Notice._cron_check_hire_notice_deadlines()
        self.assertEqual(len(order.activity_ids.filtered(
            lambda a: a.summary in summaries)), 1)

    def test_no_reminder_when_sent(self):
        order = self._hire(start=date.today() + timedelta(days=1))
        notice = self.Notice.create_from_order(order)
        notice.action_generate_xml()
        notice.action_mark_sent()
        self.assertFalse(order.hire_notice_missing)
        self.Notice._cron_check_hire_notice_deadlines()
        self.assertFalse(order.activity_ids)

    def test_no_reminder_far_ahead(self):
        order = self._hire(start=date.today() + timedelta(days=30))
        self.Notice._cron_check_hire_notice_deadlines()
        self.assertFalse(order.activity_ids)

    def test_overdue_flag(self):
        order = self._hire(start=date.today() - timedelta(days=2))
        notice = self.Notice.create_from_order(order)
        self.assertFalse(notice.is_overdue)
        self.Notice._cron_check_hire_notice_deadlines()
        self.assertTrue(notice.is_overdue)
        notice.action_generate_xml()
        notice.action_mark_sent()
        self.assertFalse(notice.is_overdue)

    def test_sent_notice_cannot_be_reset(self):
        notice = self.Notice.create_from_order(self._hire())
        notice.action_generate_xml()
        notice.action_mark_sent()
        with self.assertRaises(UserError):
            notice.action_draft()
        notice.action_mark_accepted()
        self.assertEqual(notice.state, 'accepted')

    # --- XSD -----------------------------------------------------------

    def test_xml_validates_against_xsd_if_vendored(self):
        """Офіційний XSD J3001005 ще не вендорено (tax.gov.ua — 403 для
        автоматизації). Щойно ``tests/schemas/J3001005.xsd`` з'явиться —
        тест почне валідувати згенерований XML."""
        if not os.path.exists(SCHEMA_PATH):
            self.skipTest('J3001005.xsd not vendored yet')
        notice = self.Notice.create_from_order(self._hire())
        notice.action_generate_xml()
        schema = etree.XMLSchema(etree.parse(SCHEMA_PATH))
        doc = etree.fromstring(base64.b64decode(notice.xml_file))
        self.assertTrue(schema.validate(doc), str(schema.error_log))
