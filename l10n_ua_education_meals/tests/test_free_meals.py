"""Безоплатне гаряче харчування — п. 4 Порядку № 305 (у т.ч. зміни пост. КМУ № 809)."""
from datetime import date

from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_education_meals.models.meal_free_rules import (
    education_level, universal_free_levels,
)


@tagged('post_install', '-at_install', 'l10n_ua_education_meals')
class TestFreeMealRules(TransactionCase):

    def test_levels_by_date(self):
        self.assertFalse(universal_free_levels(date(2024, 10, 4), True))
        self.assertEqual(list(universal_free_levels(date(2024, 10, 5), False)), [1, 2, 3, 4])
        # з 11.10.2025 — лише державні/комунальні
        self.assertFalse(universal_free_levels(date(2025, 10, 11), False))
        self.assertEqual(list(universal_free_levels(date(2026, 6, 26), True)), [1, 2, 3, 4])
        # пост. № 809: з 27.06.2026 — початкова, базова, профільна
        self.assertEqual(list(universal_free_levels(date(2026, 6, 27), True)),
                         list(range(1, 13)))
        self.assertFalse(universal_free_levels(date(2026, 6, 27), False))

    def test_founder_scope_only_after_809(self):
        self.assertEqual(list(universal_free_levels(date(2026, 9, 1), True, 'primary')),
                         [1, 2, 3, 4])
        self.assertFalse(universal_free_levels(date(2026, 9, 1), True, 'none'))
        # до 27.06.2026 рішення засновника не звужує гарантію для початкових класів
        self.assertEqual(list(universal_free_levels(date(2026, 3, 1), True, 'none')),
                         [1, 2, 3, 4])

    def test_education_level(self):
        self.assertEqual(education_level(4), 'primary')
        self.assertEqual(education_level(5), 'basic')
        self.assertEqual(education_level(9), 'basic')
        self.assertEqual(education_level(10), 'profile')
        self.assertFalse(education_level(0))


@tagged('post_install', '-at_install', 'l10n_ua_education_meals')
class TestFreeMealAttendance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'l10n_ua_education_type': 'zzso',
            'l10n_ua_education_is_state': True,
            'l10n_ua_meal_universal_scope': 'by_law',
        })
        cls.year = cls.env['l10n_ua.education.academic.year'].create({
            'name': 'TEST 184', 'year_start': 2184,
            'date_start': '2025-09-01', 'date_end': '2027-06-30',
            'company_id': cls.company.id,
        })
        Group = cls.env['l10n_ua.education.group']
        cls.class_3 = Group.create({'name': '3-А', 'group_type': 'class', 'level': 3,
                                    'academic_year_id': cls.year.id})
        cls.class_7 = Group.create({'name': '7-Б', 'group_type': 'class', 'level': 7,
                                    'academic_year_id': cls.year.id})
        cls.class_10 = Group.create({'name': '10-А', 'group_type': 'class', 'level': 10,
                                     'academic_year_id': cls.year.id})
        cls.pupil_3 = cls._pupil('Учень 3', cls.class_3)
        cls.pupil_7 = cls._pupil('Учень 7', cls.class_7)
        cls.pupil_7_idp = cls._pupil('Учень 7 ВПО', cls.class_7)
        cls.pupil_10 = cls._pupil('Учень 10', cls.class_10)
        cls.env['l10n_ua.meal.benefit'].create({
            'member_id': cls.pupil_7_idp.id,
            'category_id': cls.env.ref('l10n_ua_education_meals.benefit_idp_war').id,
            'date_from': '2025-09-01',
            'document': 'Довідка ВПО № 1',
        })

    @classmethod
    def _pupil(cls, name, group):
        partner = cls.env['res.partner'].create({'name': name})
        return cls.env['l10n_ua.education.contingent.member'].create({
            'partner_id': partner.id, 'member_type': 'pupil', 'state': 'studying',
            'academic_year_id': cls.year.id, 'group_id': group.id,
        })

    def _attendance(self, group, day):
        att = self.env['l10n_ua.meal.attendance'].create({
            'date': day, 'group_id': group.id})
        att.action_fill_lines()
        return att

    def test_benefit_categories_seeded(self):
        cats = self.env['l10n_ua.meal.benefit.category'].search([])
        self.assertGreaterEqual(len(cats), 8)

    def test_before_809_only_primary(self):
        att7 = self._attendance(self.class_7, '2026-05-15')
        line = att7.line_ids.filtered(lambda line: line.member_id == self.pupil_7)
        self.assertEqual(line.free_basis, 'none')
        self.assertEqual((line.free_count, line.paid_count), (0, 1))
        att3 = self._attendance(self.class_3, '2026-05-15')
        self.assertEqual(att3.line_ids.free_basis, 'universal')
        self.assertEqual(att3.free_universal_portion_count, 1)

    def test_after_809_basic_and_profile(self):
        att7 = self._attendance(self.class_7, '2026-09-01')
        line = att7.line_ids.filtered(lambda line: line.member_id == self.pupil_7)
        self.assertEqual(line.free_basis, 'universal')
        self.assertEqual((line.free_count, line.paid_count), (1, 0))
        att10 = self._attendance(self.class_10, '2026-09-01')
        self.assertEqual(att10.line_ids.free_basis, 'universal')

    def test_universal_is_one_meal_only(self):
        att = self._attendance(self.class_10, '2026-09-01')
        att.line_ids.write({'breakfast': True, 'lunch': True, 'afternoon': True})
        self.assertEqual((att.line_ids.free_count, att.line_ids.paid_count), (1, 2))
        self.assertEqual(att.lunch_count, 1)
        self.assertEqual(att.breakfast_count, 1)
        self.assertEqual(att.present_count, 1)
        self.assertEqual(att.paid_portion_count, 2)

    def test_benefit_all_meals_free(self):
        att = self._attendance(self.class_7, '2026-05-15')
        line = att.line_ids.filtered(lambda line: line.member_id == self.pupil_7_idp)
        line.write({'breakfast': True, 'lunch': True})
        self.assertEqual(line.free_basis, 'benefit')
        self.assertEqual(line.benefit_category_id,
                         self.env.ref('l10n_ua_education_meals.benefit_idp_war'))
        self.assertEqual((line.free_count, line.paid_count), (2, 0))
        self.assertEqual(att.free_benefit_portion_count, 2)
        self.assertEqual(att.free_pupil_count, 1)

    def test_benefit_period_ends(self):
        self.pupil_7_idp.meal_benefit_ids.date_to = '2026-05-31'
        att = self._attendance(self.class_7, '2026-05-15')
        att2 = self._attendance(self.class_7, '2026-06-15')
        get = lambda a: a.line_ids.filtered(lambda line: line.member_id == self.pupil_7_idp)
        self.assertEqual(get(att).free_basis, 'benefit')
        self.assertEqual(get(att2).free_basis, 'none')

    def test_absent_not_counted(self):
        att = self._attendance(self.class_3, '2026-09-01')
        att.line_ids.present = False
        self.assertEqual(att.present_count, 0)
        self.assertEqual(att.free_portion_count, 0)
        self.assertEqual(att.lunch_count, 0)

    def test_private_school_no_universal(self):
        self.company.l10n_ua_education_is_state = False
        att = self._attendance(self.class_3, '2026-09-01')
        self.assertEqual(att.line_ids.free_basis, 'none')

    def test_founder_scope_primary(self):
        self.company.l10n_ua_meal_universal_scope = 'primary'
        att = self._attendance(self.class_7, '2026-09-01')
        line = att.line_ids.filtered(lambda line: line.member_id == self.pupil_7)
        self.assertEqual(line.free_basis, 'none')

    def test_manual_counts_without_lines(self):
        att = self.env['l10n_ua.meal.attendance'].create({
            'date': '2026-09-01', 'group_id': self.class_7.id,
            'present_count': 20, 'lunch_count': 19})
        self.assertEqual((att.present_count, att.lunch_count), (20, 19))
        att.lunch_count = 18
        self.assertEqual(att.lunch_count, 18)
        self.assertEqual(att.free_portion_count, 0)
