"""Multi-company record-rule presence (issue #178)."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBonusMultiCompanyRules(TransactionCase):

    def test_rules_exist_and_are_global(self):
        refs = [
            'l10n_ua_hr_salary_bonus.hr_bonus_company_rule',
            'l10n_ua_hr_salary_bonus.hr_bonus_type_company_rule',
        ]
        for ref in refs:
            rule = self.env.ref(ref)
            self.assertTrue(rule, f"Rule {ref} must exist")
            self.assertEqual(
                rule.kind, 'restriction',
                f"Rule {ref} must be a restriction")
