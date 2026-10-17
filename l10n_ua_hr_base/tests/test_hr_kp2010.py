"""Tests for hr.kp2010 hierarchy (#98) per ДК 003:2010."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrKp2010Hierarchy(TransactionCase):
    """#98 — 4-level hierarchy for KP 2010 (Classifier of Professions)."""

    def test_intermediate_levels_created(self):
        """Migration повинна створити intermediate level-1/2/3 records."""
        level1 = self.env['hr.kp2010'].search([('level', '=', '1')])
        level2 = self.env['hr.kp2010'].search([('level', '=', '2')])
        level3 = self.env['hr.kp2010'].search([('level', '=', '3')])
        self.assertTrue(level1, 'Level 1 records (Розділи) must exist')
        self.assertTrue(level2, 'Level 2 records (Підрозділи) must exist')
        self.assertTrue(level3, 'Level 3 records (Класи) must exist')

    def test_parent_id_set_for_professions(self):
        """Кожна level-4 професія повинна мати parent_id (level-3 клас)."""
        prof = self.env['hr.kp2010'].search([('level', '=', '4')], limit=10)
        for rec in prof:
            self.assertTrue(rec.parent_id,
                             f'Профессія {rec.code} повинна мати parent_id')
            self.assertIn(rec.parent_id.level, ('3', '2', '1'),
                           f'parent_id для {rec.code} повинен бути вищого рівня')

    def test_level_computed_from_code(self):
        """`level` field обчислюється з довжини digit-prefix коду."""
        # Test the compute logic directly on a new record (not stored)
        rec = self.env['hr.kp2010'].new({'code': '2132.2'})
        rec._compute_level()
        self.assertEqual(rec.level, '4')

        rec = self.env['hr.kp2010'].new({'code': '213'})
        rec._compute_level()
        self.assertEqual(rec.level, '3')

        rec = self.env['hr.kp2010'].new({'code': '21'})
        rec._compute_level()
        self.assertEqual(rec.level, '2')

        rec = self.env['hr.kp2010'].new({'code': '2'})
        rec._compute_level()
        self.assertEqual(rec.level, '1')

    def test_parent_chain_consistent(self):
        """Перехід child → parent → parent → ... має правильно зменшувати level."""
        prof = self.env['hr.kp2010'].search([('level', '=', '4')], limit=1)
        if prof:
            current = prof
            levels_seen = []
            while current.parent_id:
                levels_seen.append(current.level)
                current = current.parent_id
            levels_seen.append(current.level)  # top
            # Levels должны идти от высшего (4) до низшего (1) монотонно
            self.assertEqual(levels_seen[0], '4')
            self.assertEqual(levels_seen[-1], '1')

    def test_parent_path_populated(self):
        """`_parent_store=True` має заповнити parent_path для всіх записів."""
        prof = self.env['hr.kp2010'].search([('level', '=', '4')], limit=1)
        if prof:
            self.assertTrue(prof.parent_path,
                             'parent_path має бути заповненим для level-4 records')


@tagged('post_install', '-at_install')
class TestHrKp2010Levels(TransactionCase):
    """#265 — офіційні назви рівнів і вибір лише професії в посаді."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kp = cls.env['hr.kp2010'].with_context(active_test=False)

    def _level(self, code):
        record = self.Kp.search([('code', '=', code)], order='id', limit=1)
        self.assertTrue(record, f'Рівень {code} має існувати')
        return record

    def test_levels_carry_official_names(self):
        """Розділ, підрозділ і клас звуться як у ДК 003:2010, а не номером."""
        self.assertEqual(self._level('2').name, 'Професіонали')
        self.assertEqual(
            self._level('21').name,
            'Професіонали в галузі фізичних, математичних та технічних наук')
        self.assertEqual(
            self._level('213').name,
            "Професіонали в галузі обчислень (комп'ютеризації)")

    def test_no_placeholder_where_official_name_exists(self):
        """Заглушка лишається лише там, де класифікатор назви не дає."""
        official = self.Kp._l10n_ua_level_names()
        placeholders = self.Kp.search([
            ('level', 'in', ('1', '2', '3')),
        ]).filtered(lambda r: r.name in ('Розділ ' + r.code,
                                         'Підрозділ ' + r.code,
                                         'Клас ' + r.code))
        self.assertFalse(
            [code for code in placeholders.mapped('code') if code in official],
            'Рівні з офіційною назвою не повинні зватися номером')

    def test_existing_placeholders_renamed_on_update(self):
        """База з ієрархією до #265: заглушки в обох мовах замінюються."""
        level = self._level('21')
        job = self.env['hr.job'].create({'name': 'Посада на підрозділі',
                                         'kp_id': level.id})
        job.flush_recordset()
        self.env.cr.execute(
            "UPDATE hr_job SET kp_name = 'Підрозділ 21' WHERE id = %s",
            (job.id,))
        job.invalidate_recordset(['kp_name'])
        self.env.cr.execute(
            "UPDATE hr_kp2010 SET name = %s::jsonb WHERE id = %s",
            ('{"en_US": "Підрозділ 21", "uk_UA": "Підрозділ 21"}', level.id))
        level.invalidate_recordset(['name'])
        self.assertEqual(self.Kp._l10n_ua_name_levels(), 1)
        self.env.cr.execute(
            "SELECT name FROM hr_kp2010 WHERE id = %s", (level.id,))
        names = self.env.cr.fetchone()[0]
        expected = 'Професіонали в галузі фізичних, математичних та технічних наук'
        self.assertEqual(names, {'en_US': expected, 'uk_UA': expected})
        self.assertEqual(job.kp_name, expected,
                         'Збережена назва КП у посаді теж оновлюється')
        self.assertEqual(self.Kp._l10n_ua_name_levels(), 0,
                         'Повторний запуск нічого не пише')

    def test_manual_level_name_kept(self):
        """Назву, яку виправила людина, оновлення модуля не перетирає."""
        level = self._level('3')
        level.name = 'Фахівці (наша назва)'
        self.Kp._l10n_ua_name_levels()
        level.invalidate_recordset(['name'])
        self.assertEqual(level.name, 'Фахівці (наша назва)')

    def test_job_offers_only_professions(self):
        """Поле професії в посаді не пропонує розділ, підрозділ чи клас."""
        # Той самий домен, що отримує клієнт для випадного списку.
        domain = self.env['hr.job'].fields_get(['kp_id'])['kp_id']['domain']
        self.assertTrue(domain, 'Поле kp_id має обмежувати вибір доменом')
        offered = self.Kp.search(domain + [('code', 'in', ('2', '21', '213'))])
        self.assertFalse(offered, 'Рівні не можна обрати як професію')
        self.assertTrue(self.Kp.search(domain + [('level', '=', '4')], limit=1))
        self.assertFalse(self.Kp.search(domain + [('level', '!=', '4')], limit=1))

    def test_job_linked_to_level_stays_valid(self):
        """Посада, що вже стоїть на рівні, редагується без помилок."""
        level = self._level('2')
        job = self.env['hr.job'].create({'name': 'Посада на розділі',
                                         'kp_id': level.id})
        job.write({'name': 'Посада на розділі (перейменована)'})
        self.assertEqual(job.kp_id, level)
        self.assertEqual(job.kp_code, '2')
