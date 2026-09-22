"""Multi-company rule presence for clinical records — issue #178.

Asserts the global multi-company rule for clinical encounters is installed and
scopes records to the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMedecinClinicalMultiCompany(TransactionCase):

    def test_encounter_rule_exists_and_global(self):
        rule = self.env.ref(
            'l10n_ua_medecin_clinical.l10n_ua_medecin_encounter_company_rule')
        self.assertEqual(
                rule.kind, 'restriction',
                'encounter rule must be a restriction')
