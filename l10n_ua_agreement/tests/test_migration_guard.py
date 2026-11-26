import importlib.util
from pathlib import Path

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.sql import table_exists

_PATH = Path(__file__).parents[1] / 'migrations' / '20.0.2.0.0' / 'pre-migration.py'
_spec = importlib.util.spec_from_file_location('l10n_ua_agreement_pre_20_2', _PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@tagged('post_install', '-at_install')
class TestMigrationGuard(TransactionCase):
    """Рішення №7: оновлення 1.x -> 2.0 у 20.0 не губить договори OCA мовчки.

    OCA у тестовому addons-path немає, тому стан «OCA встановлено» імітуємо
    рядком у ir_module_module і таблицею agreement з демо-записом; транзакція
    тесту відкочується."""

    def _fake_oca(self, rows):
        cr = self.env.cr
        cr.execute("SELECT id FROM ir_module_module WHERE name = 'agreement'")
        if cr.fetchone():
            cr.execute("UPDATE ir_module_module SET state = 'installed' WHERE name = 'agreement'")
        else:
            cr.execute("""
                INSERT INTO ir_module_module (name, state, latest_version)
                VALUES ('agreement', 'installed', '20.0.1.0.0')
            """)
        if not table_exists(cr, 'agreement'):
            cr.execute("CREATE TABLE agreement (id serial PRIMARY KEY, name varchar)")
        for i in range(rows):
            cr.execute("INSERT INTO agreement (name) VALUES (%s)", (f'Демо {i}',))

    def test_clean_base_passes(self):
        # Чиста база 20.0: OCA не встановлено — оновлення проходить.
        guard.migrate(self.env.cr, '20.0.1.1.0')

    def test_fresh_install_passes(self):
        guard.migrate(self.env.cr, None)

    def test_oca_with_records_stops(self):
        self._fake_oca(1)
        with self.assertRaisesRegex(UserError, 'договорів OCA'):
            guard.migrate(self.env.cr, '20.0.1.1.0')

    def test_oca_empty_passes(self):
        self._fake_oca(0)
        guard.migrate(self.env.cr, '20.0.1.1.0')

    def test_already_migrated_in_19_passes(self):
        # База, оновлена через 19.0.2.0.0: договори вже перенесено там.
        self._fake_oca(1)
        guard.migrate(self.env.cr, '19.0.2.0.0')

    def test_module_major(self):
        self.assertEqual(guard._module_major('20.0.1.1.0'), 1)
        self.assertEqual(guard._module_major('19.0.2.0.0'), 2)
        self.assertEqual(guard._module_major('1.1.0'), 1)
