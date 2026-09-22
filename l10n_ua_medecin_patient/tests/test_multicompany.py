"""Multi-company isolation for medical patient records — issue #178.

Medical data is especially sensitive: without record rules the patient and
declaration records were visible across ALL companies, including non-UA ones.
These tests assert the global multi-company rules scope each record to the
user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMedecinPatientMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Clinic (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.partner = cls.env['res.partner'].create({'name': 'Patient (test)'})
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'medecin_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref(
                    'l10n_ua_medecin_base.group_ua_medecin_user').id])],
        })

    def _patient(self, company):
        return self.env['l10n_ua.medecin.patient'].create({
            'partner_id': self.partner.id,
            'company_id': company.id,
        })

    def test_rules_exist_and_global(self):
        """Both multi-company rules must be present and global."""
        for xmlid in (
            'l10n_ua_medecin_patient_company_rule',
            'l10n_ua_medecin_declaration_company_rule',
        ):
            rule = self.env.ref('l10n_ua_medecin_patient.%s' % xmlid)
            self.assertEqual(
                rule.kind, 'restriction',
                '%s must be a restriction' % xmlid)

    def test_other_company_user_cannot_see_ua_patient(self):
        """A user of the non-UA company must not see the UA clinic's patient."""
        patient = self._patient(self.company_ua)
        visible = self.env['l10n_ua.medecin.patient'] \
            .with_user(self.user_other).search([])
        self.assertNotIn(patient, visible)

    def test_same_company_user_sees_own_patient(self):
        """The rule still lets a user see their own company's patient."""
        patient = self._patient(self.company_other)
        visible = self.env['l10n_ua.medecin.patient'] \
            .with_user(self.user_other).search([])
        self.assertIn(patient, visible)
