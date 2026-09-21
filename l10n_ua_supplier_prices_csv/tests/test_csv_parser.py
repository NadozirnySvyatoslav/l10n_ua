"""Тести CSV парсера."""

import base64
import json

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCsvParser(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'CSV Supplier',
            'supplier_rank': 1,
        })
        cls.uah = cls.env.ref('base.UAH')

    def _make_source(self, parser_config, with_header=True):
        fields_spec = [
            (0, 0, {'target': 'sku', 'source_path': 'SKU' if with_header else '0',
                    'required': True}),
            (0, 0, {'target': 'name', 'source_path': 'Name' if with_header else '1'}),
            (0, 0, {'target': 'price', 'source_path': 'Price' if with_header else '2',
                    'required': True, 'transform': 'to_float'}),
        ]
        mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'CSV Test Mapping',
            'parser_config': json.dumps(parser_config),
            'field_ids': fields_spec,
        })
        return self.env['l10n_ua.supplier.price.source'].create({
            'name': 'CSV Source',
            'partner_id': self.partner.id,
            'parser_type': 'csv',
            'fetcher_type': 'manual',
            'mapping_id': mapping.id,
            'currency_default_id': self.uah.id,
        })

    def _make_import(self, source, content, filename='test.csv', encoding='utf-8'):
        raw = content.encode(encoding)
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': source.id,
            'raw_file': base64.b64encode(raw).decode(),
            'raw_filename': filename,
        })
        imp._set_state('fetching')
        imp._set_state('fetched')
        return imp

    def test_csv_with_header_comma_delimiter(self):
        source = self._make_source({'delimiter': ',', 'has_header': True})
        content = "SKU,Name,Price\nSKU001,Product A,100.50\nSKU002,Product B,250.00\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].supplier_sku, 'SKU001')
        self.assertEqual(imp.line_ids[0].price, 100.50)
        self.assertEqual(imp.line_ids[1].supplier_name, 'Product B')

    def test_csv_with_semicolon_delimiter(self):
        source = self._make_source({'delimiter': ';', 'has_header': True})
        content = "SKU;Name;Price\nSKU001;Виріб А;100.50\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(imp.line_ids.supplier_name, 'Виріб А')

    def test_csv_without_header_index_path(self):
        source = self._make_source(
            {'delimiter': ',', 'has_header': False},
            with_header=False,
        )
        content = "SKU001,Product A,100.50\nSKU002,Product B,250.00\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].supplier_sku, 'SKU001')
        self.assertEqual(imp.line_ids[0].price, 100.50)

    def test_csv_windows1251_encoding(self):
        source = self._make_source({'delimiter': ';', 'encoding': 'windows-1251'})
        content = "SKU;Name;Price\nSKU001;Гайка М8;15.50\n"
        imp = self._make_import(source, content, encoding='windows-1251')
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(imp.line_ids.supplier_name, 'Гайка М8')

    def test_csv_fallback_encoding(self):
        """Declared utf-8 but file is windows-1251 — fallback має спрацювати."""
        source = self._make_source({'delimiter': ';', 'encoding': 'utf-8'})
        content = "SKU;Name;Price\nSKU001;Болт М10;22.00\n"
        imp = self._make_import(source, content, encoding='windows-1251')
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(imp.line_ids.supplier_name, 'Болт М10')

    def test_csv_comma_decimal_separator(self):
        """Українські прайси часто мають коми в цінах: 15,50."""
        mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'CSV UA Decimal',
            'parser_config': json.dumps({'delimiter': ';', 'has_header': True}),
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'SKU', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': 'Price',
                        'required': True, 'transform': 'to_float'}),
            ],
        })
        source = self.env['l10n_ua.supplier.price.source'].create({
            'name': 'UA Decimal Source',
            'partner_id': self.partner.id,
            'parser_type': 'csv',
            'mapping_id': mapping.id,
        })
        content = "SKU;Price\nSKU001;15,50\nSKU002;100,00\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(imp.line_ids[0].price, 15.50)
        self.assertEqual(imp.line_ids[1].price, 100.00)

    def test_csv_skip_rows(self):
        """Перші 2 рядки — метадані, skip_rows=2."""
        source = self._make_source({'delimiter': ',', 'skip_rows': 2, 'has_header': True})
        content = (
            "Metadata line 1\n"
            "Metadata line 2\n"
            "SKU,Name,Price\n"
            "SKU001,Product A,100.50\n"
        )
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 1)

    def test_csv_missing_required_sets_error(self):
        source = self._make_source({'delimiter': ','})
        content = "SKU,Name,Price\n,Product A,100\n"  # empty SKU
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('missing', imp.error_log)

    def test_csv_empty_parser_config_uses_defaults(self):
        """Без parser_config повинно працювати з defaults (, + utf-8 + has_header)."""
        mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'CSV Defaults',
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'SKU', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': 'Price',
                        'required': True, 'transform': 'to_float'}),
            ],
        })
        source = self.env['l10n_ua.supplier.price.source'].create({
            'name': 'Defaults Source',
            'partner_id': self.partner.id,
            'parser_type': 'csv',
            'mapping_id': mapping.id,
        })
        content = "SKU,Price\nA,10\nB,20\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 2)

    def test_csv_invalid_parser_config_json(self):
        mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'Bad Config',
            'parser_config': '{not valid json',
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'SKU', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': 'Price',
                        'required': True, 'transform': 'to_float'}),
            ],
        })
        source = self.env['l10n_ua.supplier.price.source'].create({
            'name': 'Bad',
            'partner_id': self.partner.id,
            'parser_type': 'csv',
            'mapping_id': mapping.id,
        })
        content = "SKU,Price\nA,10\n"
        imp = self._make_import(source, content)
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('Invalid parser_config', imp.error_log)
