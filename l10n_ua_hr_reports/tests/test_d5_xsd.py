"""Валідація XML Додатка Д1 (J0510111 v11) проти офіційного XSD ДПС (#187, #210).

XSD `tests/schemas/J0510111.xsd` — з оновлення СКЗ 1.34.9.0
(tax.gov.ua/data/files/719211.zip, NSIS-інсталятор, каталог xsd/);
`common_types.xsd` — з повної версії 1.34.0.0. Публічні держсхеми,
вендоряться як тест-фікстури (docs/forms-watch-playbook.md).

До #210 тут лежала J0510210 — схема Д2 (догляд за дитиною до трьох років),
під яку й було підігнано «Д1»; звідси перевірки граф нижче.
"""

import os
from datetime import date

from lxml import etree

from odoo.tests import TransactionCase, tagged

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schemas', 'J0510111.xsd')


@tagged('post_install', '-at_install')
class TestD5XsdValidation(TransactionCase):

    def _sample_vals(self):
        return {
            'tin': '12345678',
            'c_reg': 17,
            'c_raj': 16,
            'period_month': 6,
            'period_type': 1,
            'period_year': 2025,
            'c_sti_orig': '1716',
            'hzy': 2025,
            'hzm': 6,
            'hname': 'ТОВ Тест',
            'htin': '12345678',
            'hfill': date.today().strftime('%d%m%Y'),
            'hkbos': '2940910418',
            'hbos': 'Петренко О.М.',
            'hkbuh': '3184710691',
            'hbuh': 'Іваненко Н.П.',
            'persons': [
                {'rnokpp': '3184710691', 'last_name': 'Петренко',
                 'first_name': 'Олександр', 'middle_name': 'Миколайович',
                 'zo_category': 1, 'citizen': 1, 'gender': 1,
                 'employment_days': 30, 'gross': 25000.0, 'esv_base': 25000.0,
                 'esv_withheld': 0.0, 'esv_amount': 5500.0,
                 'main_job': 1, 'part_time': 0, 'special_stage': 0,
                 'new_workplace': 0, 'unfixed_hours': 0},
                {'rnokpp': '2940910418', 'last_name': 'Коваль',
                 'first_name': 'Ірина', 'middle_name': '',
                 'zo_category': 26, 'citizen': 1, 'gender': 0,
                 'employment_days': 12, 'sick_days': 3,
                 'gross': 6000.0, 'esv_base': 6000.0, 'min_wage_diff': 2000.0,
                 'esv_withheld': 0.0, 'esv_amount': 1760.0,
                 'main_job': 0, 'part_time': 1, 'special_stage': 0,
                 'new_workplace': 0, 'unfixed_hours': 0},
            ],
        }

    def _schema(self):
        return etree.XMLSchema(etree.parse(SCHEMA_PATH))

    def _validate(self, vals):
        xml = self.env['hr.report.d5']._render_d1_xml(vals)
        # Подання йде у windows-1251 — валідуємо саме ті байти, що підуть у ДПС.
        doc = etree.fromstring(xml.encode('windows-1251'))
        schema = self._schema()
        self.assertTrue(
            schema.validate(doc),
            'XSD-невалідний XML: %s' % schema.error_log)

    def test_full_validates(self):
        self._validate(self._sample_vals())

    def test_empty_persons_validates(self):
        vals = self._sample_vals()
        vals['persons'] = []
        self._validate(vals)

    def test_without_accountant_validates(self):
        vals = self._sample_vals()
        vals['hkbuh'] = ''
        vals['hbuh'] = ''
        self._validate(vals)

    def test_fixed_head_codes(self):
        xml = self.env['hr.report.d5']._render_d1_xml(self._sample_vals())
        self.assertIn('<C_DOC>J05</C_DOC>', xml)
        self.assertIn('<C_DOC_SUB>101</C_DOC_SUB>', xml)
        self.assertIn('<C_DOC_VER>11</C_DOC_VER>', xml)

    def test_columns_follow_d1_form(self):
        """Графи Д1, а не Д2: РНОКПП у гр. 07, суми в 16–20, підсумки R01G16..G20."""
        xml = self.env['hr.report.d5']._render_d1_xml(self._sample_vals())
        doc = etree.fromstring(xml.encode('windows-1251'))
        body = doc.find('DECLARBODY')
        self.assertEqual(body.find('T1RXXXXG7S[@ROWNUM="1"]').text, '3184710691')
        self.assertEqual(body.find('T1RXXXXG16[@ROWNUM="2"]').text, '6000.00')
        self.assertEqual(body.find('T1RXXXXG18[@ROWNUM="2"]').text, '2000.00')
        self.assertEqual(body.find('T1RXXXXG12[@ROWNUM="2"]').text, '3')
        self.assertIsNone(body.find('T1RXXXXG12[@ROWNUM="1"]'))
        self.assertEqual(body.find('R01G16').text, '31000.00')
        self.assertEqual(body.find('R01G20').text, '7260.00')
        # Колонки Д2 (G6S/G71S…) зникли.
        self.assertIsNone(body.find('T1RXXXXG6S'))
        self.assertIsNone(body.find('T1RXXXXG71S'))
