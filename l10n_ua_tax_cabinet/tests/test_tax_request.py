"""Тести інформаційного запиту до ДПС (l10n_ua.tax.request, J1300205).

Покриття:
- XSD-валідність згенерованого XML проти офіційного XSD ДПС;
- генерація XML + збереження у xml_file/xml_filename;
- відсутність обов'язкових реквізитів → UserError (жодного фейку);
- wiring підпису: action_submit відкриває універсальний діалог,
  _dps_on_submitted фіксує стан і квитанцію.
"""

import os
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schemas', 'J1300205.xsd')


@tagged('post_install', '-at_install')
class TestTaxRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'edrpou': '12345678', 'tax_office_code': '1716'})
        # Конфігурація кабінету потрібна для подання, і тест має заводити її
        # сам: доти вона бралася з бази, тобто ці два тести проходили лише
        # там, де конфіг лишив по собі хтось інший (тести l10n_ua_account_vat).
        # UNIQUE(company_id) — переуживаємо наявний рядок, якщо він є.
        config = cls.env['l10n_ua.tax.cabinet.config'].with_context(
            active_test=False).search([('company_id', '=', cls.company.id)], limit=1)
        vals = {'name': 'Кабінет (тест запиту)', 'taxpayer_code': '12345678',
                'active': True}
        if config:
            config.write(vals)
        else:
            cls.env['l10n_ua.tax.cabinet.config'].create(
                {**vals, 'company_id': cls.company.id})

    def _request(self, **kw):
        vals = {
            'request_type': 'j1300205',
            'request_date': date(2025, 6, 10),
            'company_id': self.company.id,
        }
        vals.update(kw)
        return self.env['l10n_ua.tax.request'].create(vals)

    def test_generate_xml_validates_against_xsd(self):
        req = self._request()
        req.action_generate_xml()
        self.assertEqual(req.state, 'generated')
        self.assertTrue(req.xml_file)
        self.assertTrue(req.xml_filename.startswith('J13002'))
        xml = req.xml_file.content
        schema = etree.XMLSchema(etree.parse(SCHEMA_PATH))
        doc = etree.fromstring(xml)  # байти вже windows-1251 з декларацією
        self.assertTrue(schema.validate(doc),
                        'XSD-невалідний XML: %s' % schema.error_log)

    def test_missing_company_data_raises(self):
        # Прибрати всі джерела ЄДРПОУ (edrpou + vat).
        self.company.write({'edrpou': False, 'vat': False})
        req = self._request()
        with self.assertRaises(UserError):
            req.action_generate_xml()

    def test_action_submit_opens_sign_dialog(self):
        req = self._request()
        action = req.action_submit()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params'], {
            'model': 'l10n_ua.tax.request', 'res_id': req.id})
        # XML сформовано під час підготовки, статус ще не «подано».
        self.assertTrue(req.xml_file)
        self.assertNotEqual(req.state, 'submitted')

    def test_prepare_signing_payload(self):
        req = self._request()
        data = req.kep_prepare_signing()
        self.assertEqual(len(data['documents']), 1)
        doc = data['documents'][0]
        self.assertEqual(doc['name'], 'doc')
        self.assertEqual(doc['format'], 'envelope')
        self.assertTrue(doc['data_b64'])

    def test_on_submitted_sets_state(self):
        req = self._request()
        req.action_generate_xml()
        req._dps_on_submitted('Квитанція: прийнято')
        self.assertEqual(req.state, 'submitted')
        self.assertTrue(req.submission_date)
        self.assertIn('прийнято', req.response_receipt)
