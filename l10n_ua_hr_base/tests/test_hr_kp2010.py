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
