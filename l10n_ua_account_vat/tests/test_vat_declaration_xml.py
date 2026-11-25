"""XML декларації з ПДВ (J0200126) і Д1 (J0200526): рядки, XSD, подання пакетом.

XSD у `tests/schemas` — контрольні схеми з пакета СКЗ ДПС (повна версія
1.34.0.0, tax.gov.ua/data/files/627351.zip), форма за наказом № 400.
"""

import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SCHEMAS = os.path.join(os.path.dirname(__file__), 'schemas')
CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'


def _schema(name):
    return etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, name)))


@tagged('post_install', '-at_install')
class TestVatDeclarationXml(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        office = cls.env['l10n_ua.tax.office'].search([('code', '=', '2650')], limit=1) or \
            cls.env['l10n_ua.tax.office'].create({'name': 'ГУ ДПС у м. Києві', 'code': '2650'})
        cls.company.write({
            'l10n_ua_is_vat_payer': True,
            'edrpou': '12345678',
            'l10n_ua_vat_ipn': '123456789012',
            'l10n_ua_tax_office_id': office.id,
            'city': 'Київ', 'street': 'вул. Хрещатик, 1', 'zip': '01001',
        })
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'ТОВ Постачальник', 'ipn': '987654321098'})
        cls.supplier2 = cls.env['res.partner'].create(
            {'name': 'ТОВ Другий постачальник', 'ipn': '111111111111'})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'ТОВ Покупець', 'ipn': '222222222222'})
        cls.period = cls.env['l10n_ua.tax.period'].create({
            'name': 'Вересень 2026', 'date_start': date(2026, 9, 1),
            'date_end': date(2026, 9, 30), 'period_type': 'month', 'month': 9,
            'year': 2026, 'quarter': 3, 'company_id': cls.company.id,
        })
        Register = cls.env['l10n_ua.vat.register']
        cls.issued = Register.create({'register_type': 'issued', 'period_id': cls.period.id,
                                      'company_id': cls.company.id})
        cls.received = Register.create({'register_type': 'received', 'period_id': cls.period.id,
                                        'company_id': cls.company.id})
        Line = cls.env['l10n_ua.vat.register.line']
        Line.create({'register_id': cls.issued.id, 'date': date(2026, 9, 10),
                     'partner_id': cls.customer.id, 'base_amount': 100000.40,
                     'vat_amount': 20000.08, 'base_20': 100000.40, 'vat_20': 20000.08})
        for partner, day, base, vat in ((cls.supplier, 5, 30000.0, 6000.0),
                                        (cls.supplier, 20, 10000.25, 2000.05),
                                        (cls.supplier2, 12, 5000.0, 1000.0)):
            Line.create({'register_id': cls.received.id, 'date': date(2026, 9, day),
                         'partner_id': partner.id, 'base_amount': base, 'vat_amount': vat,
                         'base_20': base, 'vat_20': vat})
        Line.create({'register_id': cls.received.id, 'date': date(2026, 9, 25),
                     'doc_type': 'rk', 'partner_id': cls.supplier.id, 'base_amount': -1000.0,
                     'vat_amount': -200.0, 'base_20': -1000.0, 'vat_20': -200.0})

    def _declaration(self):
        decl = self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id, 'company_id': self.company.id,
            'signatory_name': 'Іван ПЕТРЕНКО', 'signatory_rnokpp': '1234567890',
        })
        decl.action_calculate()
        return decl

    def test_rows_follow_form_400(self):
        decl = self._declaration()
        self.assertEqual(decl.line_1_1_vat, 20000)       # цілі гривні
        self.assertEqual(decl.line_10_1_vat, 9000)        # 6000 + 2000.05 + 1000
        self.assertEqual(decl.line_14_vat, -200)          # отримані РК
        self.assertEqual(decl.line_17_vat, 8800)
        self.assertEqual(decl.line_18_vat, 11200)
        self.assertEqual(decl.line_19_vat, 0)

    def test_xml_is_valid_against_dps_xsd(self):
        decl = self._declaration()
        decl.action_generate_xml()
        # Odoo 20: BinaryValue — сирі байти в .content.
        main = decl.xml_file.content
        d1 = decl.d1_xml_file.content
        _schema('J0200126.xsd').assertValid(etree.fromstring(main))
        _schema('J0200526.xsd').assertValid(etree.fromstring(d1))
        # Ім'я файлу — за наказом № 729; декларація й Д1 посилаються одна на одну.
        # C_REG C_RAJ TIN C_DOC SUB VER STAN TYPE CNT PERIOD_TYPE MONTH YEAR C_STI_ORIG
        self.assertEqual(decl.xml_filename, '26500012345678J0200126100000000110920262650.xml')
        self.assertEqual(decl.d1_xml_filename, '26500012345678J0200526100000000110920262650.xml')
        self.assertIn(decl.d1_xml_filename[:-4].encode() + b'.XML', main)
        self.assertIn(decl.xml_filename[:-4].encode() + b'.XML', d1)
        root = etree.fromstring(main)
        body = root.find('DECLARBODY')
        self.assertEqual(body.findtext('R11GB'), '20000')
        self.assertEqual(body.findtext('R101GB'), '9000')
        self.assertEqual(body.findtext('R140GB'), '-200')
        self.assertEqual(body.findtext('R180GB'), '11200')
        self.assertEqual(body.findtext('HD1'), '1')

    def test_d1_groups_suppliers_by_period(self):
        decl = self._declaration()
        decl.action_generate_xml()
        body = etree.fromstring(decl.d1_xml_file.content).find('DECLARBODY')
        ipns = [el.text for el in body.findall('T21RXXXXG2')]
        self.assertEqual(sorted(ipns), ['111111111111', '987654321098'])
        supplier_row = ipns.index('987654321098') + 1
        vat = body.find(f'T21RXXXXG7[@ROWNUM="{supplier_row}"]').text
        self.assertEqual(vat, '8000.05')
        self.assertEqual(body.findtext('R021G10'), '9000')
        self.assertEqual(body.findtext('T22RXXXXG2'), '987654321098')
        self.assertEqual(body.findtext('T22RXXXXG8'), '-200.00')

    def test_missing_requisites_are_reported_together(self):
        decl = self._declaration()
        decl.signatory_rnokpp = False
        self.supplier2.ipn = False
        with self.assertRaises(UserError) as err:
            decl.action_generate_xml()
        self.assertIn('РНОКПП', str(err.exception))
        self.assertIn('ТОВ Другий постачальник', str(err.exception))

    def test_negative_value_needs_d2(self):
        decl = self._declaration()
        decl.write({'line_10_1_vat': 50000})
        self.assertEqual(decl.line_19_vat, 50000 - 20000 - 200)
        self.assertEqual(decl.line_21_vat, decl.line_19_vat)
        with self.assertRaisesRegex(UserError, 'Д2'):
            decl.action_generate_xml()

    def test_previous_negative_value_goes_to_16_1(self):
        prev_period = self.env['l10n_ua.tax.period'].create({
            'name': 'Серпень 2026', 'date_start': date(2026, 8, 1),
            'date_end': date(2026, 8, 31), 'period_type': 'month', 'month': 8,
            'year': 2026, 'quarter': 3, 'company_id': self.company.id,
        })
        prev = self.env['l10n_ua.vat.declaration'].create(
            {'period_id': prev_period.id, 'company_id': self.company.id})
        prev.write({'line_10_1_vat': 3000, 'state': 'calculated'})
        self.assertEqual(prev.line_21_vat, 3000)
        decl = self._declaration()
        self.assertEqual(decl.line_16_1_vat, 3000)
        self.assertEqual(decl.line_18_vat, 11200 - 3000)

    def test_submit_sends_declaration_and_d1_together(self):
        decl = self._declaration()
        decl.action_generate_xml()
        config = self.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if config:
            config.write(vals)
        else:
            self.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': self.company.id})
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            spec = decl.kep_prepare_signing()
        self.assertEqual([d['name'] for d in spec['documents']], ['doc', 'd1'])
        self.assertEqual(spec['documents'][1]['filename'], decl.d1_xml_filename)

        posted = {}

        def fake_post(config, content, fname, headers, extra_files=()):
            posted['files'] = [fname] + [f for _c, f in extra_files]
            return [{'status': 'OK', 'id': 1}, {'status': 'OK', 'id': 2}]

        with patch(CONFIG + '._post_report', autospec=True, side_effect=fake_post):
            decl.kep_submit_signed({'doc': 'ENV1', 'd1': 'ENV2'}, 'AUTH')
        self.assertEqual(posted['files'], [decl.xml_filename, decl.d1_xml_filename])
        self.assertEqual(decl.state, 'submitted')
