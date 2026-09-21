"""Integration tests для JSON парсера."""

import base64
import json

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestJsonParser(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Supplier',
            'supplier_rank': 1,
        })
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')

        cls.mapping = cls.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'Test JSON Mapping',
            'record_path': 'items',
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'code', 'required': True}),
                (0, 0, {'target': 'name', 'source_path': 'title', 'required': False}),
                (0, 0, {'target': 'price', 'source_path': 'price.value',
                        'required': True, 'transform': 'to_float'}),
                (0, 0, {'target': 'currency', 'source_path': 'price.currency',
                        'required': False, 'default_value': 'UAH'}),
                (0, 0, {'target': 'qty_min', 'source_path': 'min_qty',
                        'required': False, 'default_value': '1', 'transform': 'to_float'}),
            ],
        })
        cls.source = cls.env['l10n_ua.supplier.price.source'].create({
            'name': 'Test Source',
            'partner_id': cls.partner.id,
            'parser_type': 'json',
            'fetcher_type': 'manual',
            'mapping_id': cls.mapping.id,
            'currency_default_id': cls.uah.id,
        })

    def _make_import(self, payload):
        raw_b64 = base64.b64encode(json.dumps(payload).encode('utf-8')).decode()
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': self.source.id,
            'raw_file': raw_b64,
            'raw_filename': 'test.json',
        })
        imp._set_state('fetching')
        imp._set_state('fetched')
        return imp

    def test_parse_simple_payload(self):
        imp = self._make_import({
            'items': [
                {'code': 'SKU001', 'title': 'Виріб 1',
                 'price': {'value': '100.50', 'currency': 'UAH'},
                 'min_qty': 1},
                {'code': 'SKU002', 'title': 'Виріб 2',
                 'price': {'value': '250.00', 'currency': 'USD'},
                 'min_qty': 5},
            ]
        })
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 2)
        line1, line2 = imp.line_ids
        self.assertEqual(line1.supplier_sku, 'SKU001')
        self.assertEqual(line1.supplier_name, 'Виріб 1')
        self.assertEqual(line1.price, 100.50)
        self.assertEqual(line1.currency_id, self.uah)
        self.assertEqual(line2.currency_id, self.usd)
        self.assertEqual(line2.qty_min, 5.0)

    def test_parse_with_default_value(self):
        imp = self._make_import({
            'items': [{'code': 'SKU001', 'price': {'value': '100'}}],  # no min_qty, no currency
        })
        imp.action_parse()
        line = imp.line_ids
        self.assertEqual(line.qty_min, 1.0)
        self.assertEqual(line.currency_id, self.uah)

    def test_parse_missing_required_field_raises(self):
        imp = self._make_import({
            'items': [{'title': 'No SKU here'}],  # required sku missing
        })
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('missing', imp.error_log)

    def test_parse_invalid_record_path(self):
        imp = self._make_import({'wrong_root': []})
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('No records found', imp.error_log)

    def test_reparse_clears_old_lines(self):
        imp = self._make_import({
            'items': [{'code': 'SKU001', 'price': {'value': '100'}}],
        })
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 1)
        # Re-parse from parsed state — dozvoleno через STATE_TRANSITIONS
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 1)  # очищено і створено заново

    def test_parse_nested_iteration(self):
        # Окремий mapping для вкладеної структури
        nested_mapping = self.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'Nested',
            'record_path': 'data.products',
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'sku', 'required': True}),
                (0, 0, {'target': 'price', 'source_path': 'cost', 'required': True,
                        'transform': 'to_float'}),
            ],
        })
        source = self.env['l10n_ua.supplier.price.source'].create({
            'name': 'Nested Source',
            'partner_id': self.partner.id,
            'parser_type': 'json',
            'mapping_id': nested_mapping.id,
        })
        payload = {'data': {'products': [
            {'sku': 'A', 'cost': '10'},
            {'sku': 'B', 'cost': '20'},
        ]}}
        raw_b64 = base64.b64encode(json.dumps(payload).encode('utf-8')).decode()
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': source.id,
            'raw_file': raw_b64,
        })
        imp._set_state('fetching')
        imp._set_state('fetched')
        imp.action_parse()
        self.assertEqual(len(imp.line_ids), 2)
        self.assertEqual(imp.line_ids[0].supplier_sku, 'A')

    def test_parse_invalid_json(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': self.source.id,
            'raw_file': base64.b64encode(b'{invalid json').decode(),
        })
        imp._set_state('fetching')
        imp._set_state('fetched')
        imp.action_parse()
        self.assertEqual(imp.state, 'error')
        self.assertIn('Invalid JSON', imp.error_log)
