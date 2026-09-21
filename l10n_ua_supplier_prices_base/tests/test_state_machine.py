"""Тести state machine та валідації переходів."""

import base64
import json

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStateMachine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'SM Supplier', 'supplier_rank': 1,
        })
        cls.mapping = cls.env['l10n_ua.supplier.price.mapping'].create({
            'name': 'SM Mapping',
            'record_path': 'items',
            'field_ids': [
                (0, 0, {'target': 'sku', 'source_path': 'code'}),
                (0, 0, {'target': 'price', 'source_path': 'price', 'transform': 'to_float'}),
            ],
        })
        cls.source = cls.env['l10n_ua.supplier.price.source'].create({
            'name': 'SM Source',
            'partner_id': cls.partner.id,
            'mapping_id': cls.mapping.id,
        })

    def test_initial_state_is_draft(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({'source_id': self.source.id})
        self.assertEqual(imp.state, 'draft')

    def test_invalid_transition_raises(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({'source_id': self.source.id})
        with self.assertRaises(UserError):
            imp._set_state('done')  # cannot jump

    def test_restart_from_error_only(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({'source_id': self.source.id})
        with self.assertRaises(UserError):
            imp.action_restart()  # not in error state

    def test_full_pipeline(self):
        payload = {'items': [{'code': 'X', 'price': '10'}]}
        imp = self.env['l10n_ua.supplier.price.import'].create({
            'source_id': self.source.id,
            'raw_file': base64.b64encode(json.dumps(payload).encode()).decode(),
            'raw_filename': 'p.json',
        })
        imp.action_fetch()    # manual: requires raw_file (already set)
        self.assertEqual(imp.state, 'fetched')
        imp.action_parse()
        self.assertEqual(imp.state, 'parsed')
        self.assertEqual(len(imp.line_ids), 1)

    def test_fetch_manual_without_file_errors(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({'source_id': self.source.id})
        imp.action_fetch()
        self.assertEqual(imp.state, 'error')
        self.assertIn('Upload a file', imp.error_log)

    def test_sequence_generated(self):
        imp = self.env['l10n_ua.supplier.price.import'].create({'source_id': self.source.id})
        self.assertTrue(imp.name and imp.name != '/')
        self.assertIn('SPI', imp.name)
