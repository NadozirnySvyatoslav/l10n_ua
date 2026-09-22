"""Multi-company isolation for education records — issue #178.

Without record rules the education contingent/groups/years were visible across
ALL companies, including non-UA ones. These tests assert the global
multi-company rules scope each record to the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEducationMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA School (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.partner = cls.env['res.partner'].create({'name': 'Pupil (test)'})
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'edu_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('l10n_ua_education_base.group_ua_education_user').id])],
        })

    def _member(self, company):
        return self.env['l10n_ua.education.contingent.member'].create({
            'partner_id': self.partner.id,
            'member_type': 'pupil',
            'company_id': company.id,
        })

    def test_rules_exist_and_global(self):
        """All three multi-company rules must be present and global."""
        for xmlid in (
            'l10n_ua_education_academic_year_company_rule',
            'l10n_ua_education_group_company_rule',
            'l10n_ua_education_contingent_member_company_rule',
        ):
            rule = self.env.ref('l10n_ua_education_base.%s' % xmlid)
            self.assertEqual(
                rule.kind, 'restriction',
                '%s must be a restriction' % xmlid)

    def test_other_company_user_cannot_see_ua_member(self):
        """A user of the non-UA company must not see the UA company's member."""
        member = self._member(self.company_ua)
        visible = self.env['l10n_ua.education.contingent.member'] \
            .with_user(self.user_other).search([])
        self.assertNotIn(member, visible)

    def test_same_company_user_sees_own_member(self):
        """The rule still lets a user see their own company's member."""
        member = self._member(self.company_other)
        visible = self.env['l10n_ua.education.contingent.member'] \
            .with_user(self.user_other).search([])
        self.assertIn(member, visible)
