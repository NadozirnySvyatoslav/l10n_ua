from datetime import date

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTariffGrade(TransactionCase):
    """Tariff grades: hourly rates of a company, for a period."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Tariff Grade Test Company A'})
        cls.company_b = cls.env['res.company'].create({'name': 'Tariff Grade Test Company B'})
        cls.Grade = cls.env['hr.tariff.grade'].with_company(cls.company)
        # New companies get the typical set; these tests build their own.
        cls.Grade.with_context(active_test=False).search(
            [('company_id', 'in', (cls.company | cls.company_b).ids)]).unlink()

    def _grades(self, rates=((1, 1.0, 100.0), (3, 1.18, 122.0)), company=None,
                date_from=date(2026, 1, 1), date_to=False):
        return self.Grade.create([{
            'name': f'Grade {grade}', 'grade': grade, 'coefficient': coef,
            'company_id': (company or self.company).id,
            'date_from': date_from, 'date_to': date_to,
            **({'hourly_rate': rate} if rate is not None else {}),
        } for grade, coef, rate in rates])

    def _flush_tracking(self):
        # Tracking values are written by the pre-commit callbacks, which a
        # test transaction never reaches on its own.
        self.env.flush_all()
        self.env.cr.precommit.run()

    def test_computed_rate_is_first_grade_times_coefficient(self):
        grade1, grade3 = self._grades()
        self.assertAlmostEqual(grade3.computed_rate, 118.0)
        self.assertAlmostEqual(grade3.hourly_rate, 122.0, msg='the agreed rate is kept')
        self.assertAlmostEqual(grade3.rate_diff, 4.0)
        grade1.hourly_rate = 110.0
        self.assertAlmostEqual(grade3.hourly_rate, 122.0,
                               msg='a rate agreed otherwise does not follow grade 1')
        self.assertAlmostEqual(grade3.computed_rate, 129.8)
        self.assertAlmostEqual(grade3.rate_diff, -7.8)

    def test_rate_follows_first_grade_until_set_otherwise(self):
        grade1, grade2, grade3 = self._grades(
            ((1, 1.0, 100.0), (2, 1.09, None), (3, 1.18, None)))
        self.assertAlmostEqual(grade3.hourly_rate, 118.0, msg='filled from the formula')
        grade2.hourly_rate = 110.0
        grade1.hourly_rate = 120.0
        self.assertAlmostEqual(grade3.hourly_rate, 141.6)
        self.assertAlmostEqual(grade2.hourly_rate, 110.0)
        self.assertAlmostEqual(grade3.rate_diff, 0.0)
        self.assertAlmostEqual(grade2.rate_diff, -20.8)

    def test_difference_of_a_kopiyka_shows(self):
        grade3 = self._grades(((1, 1.0, 100.0), (3, 1.18, 118.01)))[1]
        self.assertAlmostEqual(grade3.rate_diff, 0.01)
        grade3.hourly_rate = 118.0
        self.assertEqual(grade3.rate_diff, 0.0)

    def test_rate_in_force_on_date(self):
        old3 = self._grades(date_to=date(2026, 6, 30))[1]
        new3 = self._grades(((1, 1.0, 120.0), (3, 1.18, 141.6)),
                            date_from=date(2026, 7, 1))[1]
        self.assertEqual(old3._l10n_ua_grade_on(date(2026, 3, 31)), old3)
        self.assertEqual(old3._l10n_ua_grade_on(date(2026, 7, 31)), new3)
        self.assertEqual(new3._l10n_ua_grade_on(date(2026, 3, 31)), old3)
        self.assertFalse(old3._l10n_ua_grade_on(date(2025, 12, 31)))

    def test_periods_of_one_grade_leave_no_gap(self):
        self._grades(date_to=date(2026, 6, 30))
        with self.assertRaises(ValidationError):
            self._grades(((3, 1.18, 130.0),), date_from=date(2026, 9, 1))
        # The day after the previous period ends is accepted.
        self._grades(((3, 1.18, 130.0),), date_from=date(2026, 7, 1))

    def test_closing_a_period_too_early_leaves_no_gap(self):
        old3 = self._grades(date_to=date(2026, 6, 30))[1]
        self._grades(((3, 1.18, 130.0),), date_from=date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            old3.date_to = date(2026, 5, 31)

    def test_first_period_starts_on_any_date(self):
        self._grades(date_from=date(2026, 5, 1))

    def test_last_period_may_stay_closed(self):
        # Giving up the tariff system is not a gap.
        self._grades(date_to=date(2026, 6, 30))

    def test_archived_period_is_not_a_neighbour(self):
        old = self._grades(date_to=date(2026, 6, 30))
        old.action_archive()
        self._grades(((3, 1.18, 130.0),), date_from=date(2026, 9, 1))

    def test_periods_of_one_grade_do_not_overlap(self):
        self._grades(date_to=date(2026, 6, 30))
        with self.assertRaises(ValidationError):
            self._grades(((3, 1.18, 130.0),), date_from=date(2026, 6, 1))
        # Another company may share the dates.
        self._grades(company=self.company_b, date_from=date(2026, 6, 1))

    def test_companies_are_independent(self):
        grades_a = self._grades()
        grades_b = self._grades(company=self.company_b)
        officer = self.env['res.users'].create({
            'name': 'Tariff officer', 'login': 'tariff_grade_test_officer',
            'company_id': self.company_b.id,
            'company_ids': [(6, 0, (self.company | self.company_b).ids)],
            'group_ids': [(6, 0, [self.env.ref('hr.group_hr_user').id])],
        })
        visible = self.env['hr.tariff.grade'].with_user(officer).with_context(
            allowed_company_ids=[self.company_b.id]).search(
            [('id', 'in', (grades_a | grades_b).ids)])
        self.assertEqual(visible, grades_b)

    def test_rate_below_subsistence_minimum_is_refused(self):
        if 'hr.psp.parameters' not in self.env:
            self.skipTest('l10n_ua_hr_salary is not installed')
        self.env['hr.psp.parameters'].create({
            'year': 2030, 'date_from': date(2030, 1, 1),
            'subsistence_minimum': 4000.0, 'min_wage': 9000.0,
            'company_id': self.company.id,
        })
        # January 2030: 23 weekdays × 8 h = 184 h; 20 × 184 = 3 680 < 4 000.
        with self.assertRaises(ValidationError):
            self._grades(((1, 1.0, 20.0),), date_from=date(2030, 1, 1))
        # A zero rate is one not entered yet.
        self._grades(((1, 1.0, 0.0),), date_from=date(2030, 1, 1))

    def test_job_uses_grades_of_its_own_company(self):
        grade_a = self._grades()[1]
        grade_b = self._grades(company=self.company_b)[1]
        job = self.env['hr.job'].create({
            'name': 'Turner', 'company_id': self.company.id,
            'tariff_grade_id': grade_a.id,
        })
        with self.assertRaises(UserError):
            job.tariff_grade_id = grade_b
        with Form(job) as form:
            form.company_id = self.company_b
            self.assertFalse(form.tariff_grade_id,
                             'a grade of the old company is cleared')

    def test_new_company_gets_the_typical_grades(self):
        company = self.env['res.company'].create({'name': 'Tariff Grade Test Company C'})
        grades = self.env['hr.tariff.grade'].search([('company_id', '=', company.id)])
        templates = self.env['hr.tariff.grade.template'].search([])
        self.assertEqual(sorted(grades.mapped(lambda g: (g.grade, g.coefficient))),
                         sorted(templates.mapped(lambda t: (t.grade, t.coefficient))))
        self.assertFalse(any(grades.mapped('hourly_rate')))
        year = fields.Date.context_today(self.env.user).year
        self.assertEqual(set(grades.mapped('date_from')), {date(year, 1, 1)})
        self.env['hr.tariff.grade']._seed_company_grades()
        self.assertEqual(self.env['hr.tariff.grade'].search_count(
            [('company_id', '=', company.id)]), len(templates))
        grades.filtered(lambda g: g.grade == 1).hourly_rate = 103.66
        self.assertAlmostEqual(grades.filtered(lambda g: g.grade == 2).hourly_rate,
                               112.99, msg='the first-grade rate fills the others')

    def test_grade_in_use_is_not_deleted(self):
        grade3 = self._grades()[1]
        self.env['hr.job'].create({
            'name': 'Turner', 'company_id': self.company.id,
            'tariff_grade_id': grade3.id,
        })
        with self.assertRaises(UserError):
            grade3.unlink()
        grade3.action_archive()
        self.assertFalse(grade3._l10n_ua_grade_on(date(2026, 5, 1)),
                         'an archived grade is in force nowhere')

    def test_unused_grade_is_deleted(self):
        self._grades()[1].unlink()

    def test_name_shows_the_period_and_search_by_number(self):
        grade3 = self._grades(date_to=date(2026, 6, 30))[1]
        self.assertEqual(grade3.display_name, 'Grade 3 (2026-01-01 – 2026-06-30)')
        open_ended = self._grades(date_from=date(2026, 7, 1))[1]
        self.assertEqual(open_ended.display_name, 'Grade 3 (2026-07-01 –)')
        found = self.Grade.name_search('3')
        self.assertIn(grade3.id, [grade_id for grade_id, _name in found])

    def test_currency_follows_the_company_not_the_switcher(self):
        usd = self.env.ref('base.USD')
        self.company_b.currency_id = usd
        grade = self.Grade.with_company(self.company).create({
            'name': 'Grade 1', 'grade': 1, 'coefficient': 1.0,
            'hourly_rate': 100.0, 'company_id': self.company_b.id,
            'date_from': date(2026, 1, 1),
        })
        self.assertEqual(grade.currency_id, usd)

    def test_rate_changes_are_logged(self):
        grade1 = self._grades()[0]
        self._flush_tracking()
        before = len(grade1.message_ids)
        grade1.hourly_rate = 110.0
        self._flush_tracking()
        self.assertEqual(len(grade1.message_ids), before + 1)
        tracked = grade1.message_ids[0].tracking_value_ids
        self.assertEqual(tracked.field_id.name, 'hourly_rate')
        self.assertAlmostEqual(tracked.old_value_float, 100.0)
        self.assertAlmostEqual(tracked.new_value_float, 110.0)


@tagged('post_install', '-at_install')
class TestTariffGradeNewPeriod(TestTariffGrade):
    """The wizard closes the grades in force and opens them anew."""

    def _wizard(self, base=120.0, date_from=date(2026, 7, 1)):
        return self.env['hr.tariff.grade.new.period'].create({
            'company_id': self.company.id,
            'date_from': date_from,
            'base_rate': base,
        })

    def test_new_period_closes_the_old_one_without_a_gap(self):
        grade1, grade3 = self._grades()
        wizard = self._wizard()
        wizard.action_apply()
        self.assertEqual(grade1.date_to, date(2026, 6, 30))
        self.assertEqual(grade3.date_to, date(2026, 6, 30))
        new3 = grade3._l10n_ua_grade_on(date(2026, 7, 31))
        self.assertNotEqual(new3, grade3)
        self.assertEqual(new3.date_from, date(2026, 7, 1))
        # A rate is in force on every date, the day of the change included.
        self.assertTrue(grade3._l10n_ua_grade_on(date(2026, 6, 30)))

    def test_rates_follow_the_new_first_grade_rate(self):
        # Grade 3 is agreed at 122.00 while the formula gives 118.00.
        grade1, grade3 = self._grades()
        wizard = self._wizard()
        lines = {line.grade: line for line in wizard.line_ids}
        self.assertAlmostEqual(lines[1].new_rate, 120.0)
        self.assertAlmostEqual(lines[3].new_rate, 122.0,
                               msg='a rate agreed otherwise is carried over')
        # A grade that followed the formula is recomputed from the new base.
        grade3.hourly_rate = grade3.computed_rate
        wizard = self._wizard()
        self.assertAlmostEqual(
            {line.grade: line for line in wizard.line_ids}[3].new_rate, 141.6)

    def test_old_rates_stay_as_they_were(self):
        grade1, grade3 = self._grades()
        self._wizard().action_apply()
        self.assertAlmostEqual(grade3.hourly_rate, 122.0)
        self.assertAlmostEqual(
            grade3._l10n_ua_grade_on(date(2026, 3, 31)).hourly_rate, 122.0)

    def test_a_later_period_stops_the_wizard(self):
        self._grades(date_to=date(2026, 6, 30))
        self._grades(date_from=date(2026, 7, 1))
        with self.assertRaises(UserError):
            self._wizard(date_from=date(2026, 7, 1)).action_apply()

    def test_company_without_grades_stops_the_wizard(self):
        with self.assertRaises(UserError):
            self._wizard().action_apply()

    def test_new_rate_below_the_subsistence_minimum_is_refused(self):
        if 'hr.psp.parameters' not in self.env:
            self.skipTest('l10n_ua_hr_salary is not installed')
        # The company already has the statutory parameters of 2026.
        params = self.env['hr.psp.parameters'].get_parameters(
            date(2026, 1, 1), self.company.id)
        params.subsistence_minimum = 4000.0
        self._grades()
        with self.assertRaises(ValidationError):
            self._wizard(base=1.0).action_apply()

    def test_the_wizard_says_where_each_new_rate_comes_from(self):
        # Grade 3 is agreed at 122.00 while the formula gives 118.00.
        self._grades()
        self._grades(((5, 1.36, None),))
        sources = {line.grade: line.rate_source
                   for line in self._wizard().line_ids}
        self.assertEqual(sources[1], 'base')
        self.assertEqual(sources[3], 'agreed',
                         'a rate agreed apart from the formula is carried over')
        self.assertEqual(sources[5], 'formula')

    def test_the_wizard_saves_from_the_form(self):
        # Form() goes through the view like the client does: a line field the
        # view does not carry is lost on save.
        self._grades()
        with Form(self.env['hr.tariff.grade.new.period']) as form:
            form.company_id = self.company
            form.date_from = date(2026, 7, 1)
            form.base_rate = 120.0
        wizard = form.record
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertTrue(all(wizard.line_ids.mapped('grade_id')))
        wizard.action_apply()
