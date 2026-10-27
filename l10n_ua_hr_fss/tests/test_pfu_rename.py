"""ФСС → ПФУ: нові номери й міграція послідовності (#499)."""

import importlib.util
import os
from datetime import date

from odoo.tests import TransactionCase, tagged

MIGRATION = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                         '19.0.1.1.0', 'post-migration.py')


def _migration():
    spec = importlib.util.spec_from_file_location('hr_fss_mig_1_1', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestPfuRename(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sequence = cls.env.ref('l10n_ua_hr_fss.seq_hr_fss_settlement')

    def test_new_number_has_pfu_prefix(self):
        st = self.env['hr.fss.settlement'].create({
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 31)})
        self.assertTrue(st.name.startswith('ПФУ/'), st.name)

    def test_visible_labels(self):
        self.assertNotIn('ФСС', self.env['ir.model']._get(
            'hr.fss.settlement').name)
        action = self.env.ref('l10n_ua_hr_fss.hr_fss_settlement_action')
        self.assertEqual(action.name, 'Взаєморозрахунки з ПФУ')

    def test_migration_updates_default_prefix(self):
        self.sequence.write({'prefix': 'ФСС/%(year)s/',
                             'name': 'FSS Settlement'})
        old_doc = self.env['hr.fss.settlement'].create({
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 31)})
        self.assertTrue(old_doc.name.startswith('ФСС/'))
        old_name = old_doc.name
        self.env.flush_all()
        _migration().migrate(self.env.cr, '19.0.1.0.0')
        self.sequence.invalidate_recordset()
        old_doc.invalidate_recordset()
        self.assertEqual(self.sequence.prefix, 'ПФУ/%(year)s/')
        self.assertEqual(self.sequence.name, 'PFU Settlement')
        self.assertEqual(old_doc.name, old_name)  # наявні номери не чіпаємо

    def test_migration_keeps_custom_prefix(self):
        self.sequence.prefix = 'ЛК/%(year)s/'
        self.env.flush_all()
        _migration().migrate(self.env.cr, '19.0.1.0.0')
        self.sequence.invalidate_recordset()
        self.assertEqual(self.sequence.prefix, 'ЛК/%(year)s/')
