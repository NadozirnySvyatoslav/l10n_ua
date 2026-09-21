"""Тести XML парсера."""

import base64
import json

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestXmlParser(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'XML Supplier', 'supplier_rank': 1,
        })
        cls.uah = cls.env.ref('base.UAH')

    def _make_source(self, record_path, fields_spec, parser_config=None):
        mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'XML Test',
            'record_path': record_path,
            'parser_config': json.dumps(parser_config or {}),
            'field_ids': fields_spec,
        })
        return self.env['l10n_ua.supplier.price.source'].create({
            'name': 'XML Source',
            'partner_id': self.partner.id,
            'parser_type': 'xml',
            'fetcher_type': 'manual',
            'mapping_id': mapping.id,
            'currency_default_id': self.uah.id,
        })

    def _make_import(self, source, content, encoding='utf-8'):
        if isinstance(content, str):
            content = content.encode(encoding)
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': source.id,
            'raw_file': base64.b64encode(content).decode(),
            'raw_filename': 'p.xml',
        })
        imp._set_state('fetching')
        imp._set_state('fetched')
        return imp

    def test_xml_text_path(self):
        source = self._make_source(
            '//product',
            [
                (0, 0, {'target': 'sku', 'source_path': './code/text()',
                        'required': True}),
                (0, 0, {'target': 'name', 'source_path': './name/text()'}),
                (0, 0, {'target': 'price', 'source_path': './price/text()',
                        'required': True, 'transform': 'to_float'}),
            ],
        )
        xml = """<?xml version="1.0"?>
<catalog>
    <product>
        <code>SKU001</code>
        <name>Виріб А</name>
        <price>100.50</price>
    </product>
    <product>
        <code>SKU002</code>
        <name>Виріб Б</name>
        <price>250.00</price>
    </product>
</catalog>"""
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].supplier_sku, 'SKU001')
        self.assertEqual(imp.line_ids[0].supplier_name, 'Виріб А')
        self.assertEqual(imp.line_ids[0].price, 100.50)

    def test_xml_attribute_path(self):
        source = self._make_source(
            '//product',
            [
                (0, 0, {'target': 'sku', 'source_path': '@code', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': '@price',
                        'required': True, 'transform': 'to_float'}),
            ],
        )
        xml = '''<?xml version="1.0"?>
<catalog>
    <product code="A1" price="10.50"/>
    <product code="A2" price="20.00"/>
</catalog>'''
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].supplier_sku, 'A1')
        self.assertEqual(imp.line_ids[1].price, 20.00)

    def test_xml_nested_attribute(self):
        source = self._make_source(
            '//item',
            [
                (0, 0, {'target': 'sku', 'source_path': './sku/text()',
                        'required': True}),
                (0, 0, {'target': 'price', 'source_path': './price/@value',
                        'required': True, 'transform': 'to_float'}),
                (0, 0, {'target': 'currency', 'source_path': './price/@currency'}),
            ],
        )
        xml = '''<?xml version="1.0"?>
<list>
    <item>
        <sku>X1</sku>
        <price value="100" currency="UAH"/>
    </item>
    <item>
        <sku>X2</sku>
        <price value="200" currency="USD"/>
    </item>
</list>'''
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].currency_id, self.uah)
        self.assertEqual(imp.line_ids[1].currency_id.name, 'USD')

    def test_xml_namespaces(self):
        source = self._make_source(
            '//ns:product',
            [
                (0, 0, {'target': 'sku', 'source_path': './ns:code/text()',
                        'required': True}),
                (0, 0, {'target': 'price', 'source_path': './ns:price/text()',
                        'required': True, 'transform': 'to_float'}),
            ],
            parser_config={'namespaces': {'ns': 'http://example.com/schema'}},
        )
        xml = '''<?xml version="1.0"?>
<catalog xmlns:ns="http://example.com/schema">
    <ns:product>
        <ns:code>NS1</ns:code>
        <ns:price>50</ns:price>
    </ns:product>
</catalog>'''
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 1)
        self.assertEqual(imp.line_ids.supplier_sku, 'NS1')

    def test_xml_windows1251_via_forced_encoding(self):
        source = self._make_source(
            '//product',
            [
                (0, 0, {'target': 'sku', 'source_path': './code/text()',
                        'required': True}),
                (0, 0, {'target': 'name', 'source_path': './name/text()'}),
                (0, 0, {'target': 'price', 'source_path': './price/text()',
                        'required': True, 'transform': 'to_float'}),
            ],
            parser_config={'encoding': 'windows-1251'},
        )
        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<catalog>'
               '<product><code>K1</code><name>Гайка М8</name><price>15.50</price></product>'
               '</catalog>')
        imp = self._make_import(source, xml, encoding='windows-1251')
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(imp.line_ids.supplier_name, 'Гайка М8')

    def test_xml_record_path_no_match(self):
        source = self._make_source(
            '//nonexistent',
            [
                (0, 0, {'target': 'sku', 'source_path': '@code', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': '@price', 'required': True,
                        'transform': 'to_float'}),
            ],
        )
        xml = '<?xml version="1.0"?><catalog><item code="X" price="1"/></catalog>'
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('No records found', imp.error_log)

    def test_xml_invalid_syntax(self):
        source = self._make_source(
            '//product',
            [(0, 0, {'target': 'sku', 'source_path': '@code', 'required': True}),
             (0, 0, {'target': 'price', 'source_path': '@price', 'required': True,
                     'transform': 'to_float'})],
        )
        imp = self._make_import(source, '<not closed')
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('Invalid XML', imp.error_log)

    def test_xml_invalid_xpath(self):
        source = self._make_source(
            '//[invalid',  # broken XPath
            [(0, 0, {'target': 'sku', 'source_path': '@code', 'required': True}),
             (0, 0, {'target': 'price', 'source_path': '@price', 'required': True,
                     'transform': 'to_float'})],
        )
        xml = '<?xml version="1.0"?><catalog><item code="X" price="1"/></catalog>'
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(imp.state, 'error')

    def test_xml_missing_required_field(self):
        source = self._make_source(
            '//product',
            [(0, 0, {'target': 'sku', 'source_path': '@missing', 'required': True}),
             (0, 0, {'target': 'price', 'source_path': '@price', 'required': True,
                     'transform': 'to_float'})],
        )
        xml = '<?xml version="1.0"?><catalog><product code="X" price="1"/></catalog>'
        imp = self._make_import(source, xml)
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('missing', imp.error_log)
