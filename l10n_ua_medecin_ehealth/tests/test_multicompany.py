"""Multi-company rule presence for eHealth declarations — issue #178.

The `l10n_ua.medecin.declaration` model is DEFINED in l10n_ua_medecin_patient
(this module only extends it for the eHealth API), so its global multi-company
rule ships in that module. This test asserts the rule is present and global so
the declaration data surfaced through the eHealth integration stays scoped to
the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMedecinEhealthMultiCompany(TransactionCase):

    def test_declaration_rule_exists_and_global(self):
        rule = self.env.ref(
            'l10n_ua_medecin_patient.l10n_ua_medecin_declaration_company_rule')
        self.assertEqual(
                rule.kind, 'restriction',
                'declaration rule must be a restriction')
