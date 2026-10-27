"""Вид нарахування SICK_FSS: «за рахунок ПФУ» і міграція назви (#499)."""

import importlib.util
import os

from odoo.tests import TransactionCase, tagged

MIGRATION = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                         '19.0.1.5.6', 'post-migration.py')


def _migrate(cr):
    spec = importlib.util.spec_from_file_location('hr_salary_mig_1_5_5',
                                                  MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(cr, '19.0.1.5.4')


@tagged('post_install', '-at_install')
class TestSickPfuRename(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sick = cls.env.ref('l10n_ua_hr_salary.accrual_type_sick_fss')

    def _set_name(self, value):
        self.env.cr.execute(
            "UPDATE hr_accrual_type SET name = jsonb_build_object("
            "'en_US', %s::text, 'uk_UA', %s::text) WHERE id = %s",
            (value, value, self.sick.id))
        self.sick.invalidate_recordset()

    def test_fresh_name(self):
        self.assertEqual(self.sick.code, 'SICK_FSS')
        self.assertIn('ПФУ', self.sick.with_context(lang='en_US').name)

    def test_migration_renames_default(self):
        self._set_name('Лікарняні (за рахунок ФСС)')
        self.sick.description = (
            'Допомога по тимчасовій непрацездатності за рахунок ФСС')
        self.env.flush_all()
        _migrate(self.env.cr)
        self.sick.invalidate_recordset()
        self.env.cr.execute(
            "SELECT name FROM hr_accrual_type WHERE id = %s", (self.sick.id,))
        self.assertEqual(self.env.cr.fetchone()[0], {
            'en_US': 'Лікарняні (за рахунок ПФУ)',
            'uk_UA': 'Лікарняні (за рахунок ПФУ)'})
        self.assertIn('ПФУ', self.sick.description)

    def test_migration_keeps_user_name(self):
        self._set_name('Лікарняні з 6-го дня')
        self.sick.description = 'Своє'
        self.env.flush_all()
        _migrate(self.env.cr)
        self.sick.invalidate_recordset()
        self.assertEqual(self.sick.with_context(lang='en_US').name,
                         'Лікарняні з 6-го дня')
        self.assertEqual(self.sick.description, 'Своє')
