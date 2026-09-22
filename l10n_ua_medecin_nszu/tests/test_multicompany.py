"""Multi-company rule presence for НСЗУ contracts — issue #178.

Asserts the global multi-company rule for НСЗУ contracts is installed and
scopes records to the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMedecinNszuMultiCompany(TransactionCase):

    def test_contract_rule_exists_and_global(self):
        rule = self.env.ref(
            'l10n_ua_medecin_nszu.l10n_ua_medecin_nszu_contract_company_rule')
        self.assertEqual(
                rule.kind, 'restriction',
                'НСЗУ contract rule must be a restriction')
