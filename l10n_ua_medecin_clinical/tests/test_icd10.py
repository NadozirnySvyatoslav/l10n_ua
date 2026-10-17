"""Повний класифікатор НК 025:2021 (МКХ-10) — issue #237."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIcd10Nk025(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Icd = cls.env['l10n_ua.medecin.icd10'].with_context(active_test=False)

    def _get(self, code):
        rec = self.Icd.search([('code', '=', code)])
        self.assertEqual(len(rec), 1, code)
        return rec

    def test_full_classifier_loaded(self):
        counts = {lvl: self.Icd.search_count([('level', '=', lvl)])
                  for lvl in ('chapter', 'block', 'category', 'subcategory', 'subcategory5')}
        self.assertEqual(counts['chapter'], 22)
        self.assertGreater(counts['block'], 250)
        self.assertGreater(counts['category'], 2000)
        self.assertGreater(counts['subcategory'], 10000)
        self.assertGreater(counts['subcategory5'], 7000)
        legacy = self.env['ir.model.data'].search([
            ('module', '=', 'l10n_ua_medecin_clinical'),
            ('model', '=', 'l10n_ua.medecin.icd10')])
        self.assertEqual(len(legacy), 27)
        self.assertTrue(all(self.Icd.browse(legacy.mapped('res_id')).mapped('level')),
                        'стартові 27 кодів знайдено в класифікаторі й оновлено')

    def test_hierarchy(self):
        q7149 = self._get('Q71.49')
        self.assertEqual(q7149.level, 'subcategory5')
        self.assertEqual(q7149.parent_id.code, 'Q71.4')
        self.assertEqual(q7149.parent_id.parent_id.code, 'Q71')
        a000 = self._get('A00.0')
        self.assertEqual(a000.parent_id.code, 'A00')
        self.assertEqual(a000.parent_id.parent_id.code, 'A00-A09')
        self.assertEqual(a000.parent_id.parent_id.parent_id.code, 'Клас 01')
        self.assertEqual(a000.block, 'A00-A09')
        # вкладені блоки класу 2: C00-C96 ⊃ C00-C75 ⊃ C00-C14
        c00 = self._get('C00')
        self.assertEqual(c00.parent_id.code, 'C00-C14')
        self.assertEqual(c00.parent_id.parent_id.code, 'C00-C75')
        self.assertEqual(c00.parent_id.parent_id.parent_id.code, 'C00-C96')
        chapter = self._get('Клас 09')
        self.assertIn(self._get('I10'), self.Icd.search([('id', 'child_of', chapter.id)]))
        self.assertFalse(self.Icd.search_count([
            ('level', 'in', ('category', 'subcategory', 'subcategory5')),
            ('parent_id', '=', False)]), 'кожна рубрика має батька')

    def test_selectable_flag(self):
        self.assertFalse(self._get('Клас 01').is_selectable)
        self.assertFalse(self._get('A00-A09').is_selectable)
        self.assertFalse(self._get('A00').is_selectable, 'A00 має підрубрики')
        self.assertTrue(self._get('A00.0').is_selectable)
        self.assertFalse(self._get('Q71.4').is_selectable)
        self.assertTrue(self._get('Q71.49').is_selectable)

    def test_legacy_xmlids_updated_in_place(self):
        """27 стартових xml-id лишаються валідними й не дублюються."""
        i10 = self.env.ref('l10n_ua_medecin_clinical.icd10_i10')
        self.assertEqual(i10.code, 'I10')
        self.assertEqual(i10.level, 'category')
        self.assertEqual(i10.parent_id.code, 'I10-I15')
        j06 = self.env.ref('l10n_ua_medecin_clinical.icd10_j06')
        self.assertEqual(j06.code, 'J06.9')
        self.assertEqual(j06.level, 'subcategory')
        self.assertEqual(self.Icd.search_count([('code', '=', 'I10')]), 1)

    def test_search_by_code_and_name(self):
        res = self.Icd.name_search('J06.9')
        self.assertIn(self._get('J06.9').id, [r[0] for r in res])
        res = self.Icd.search([('display_name', 'ilike', 'гіпертензі')])
        self.assertIn(self._get('I10'), res)
        res = self.Icd.search([('name', 'ilike', 'холер')])
        self.assertIn(self._get('A00.0'), res)

    def test_reload_idempotent_and_repairs(self):
        self.assertEqual(self.Icd._load_nk025(), (0, 0))
        i10 = self.env.ref('l10n_ua_medecin_clinical.icd10_i10')
        name, parent = i10.name, i10.parent_id
        i10.write({'name': 'Демо-назва', 'parent_id': False, 'level': False})
        custom = self.Icd.create({'code': 'ZZT.237', 'name': 'Користувацький код'})
        self.assertEqual(self.Icd._load_nk025(), (0, 1))
        self.assertEqual(i10.name, name)
        self.assertEqual(i10.parent_id, parent)
        self.assertEqual(custom.name, 'Користувацький код')

    def test_diagnosis_domain_selectable(self):
        field = self.env['l10n_ua.medecin.diagnosis']._fields['icd10_id']
        self.assertEqual(field.domain, [('is_selectable', '=', True)])
