"""Multi-company rule presence test (issue #178).

Asserts each multi-company access record exists and is a restriction.
Odoo 20 merged ir.rule into ir.access: a record without a group is a
restriction (ANDed for everyone), which is what the old global flag meant.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMultiCompanyRules(TransactionCase):

    RULE_XMLIDS = [
        'l10n_ua_hr_reports.hr_report_1df_company_rule',
        'l10n_ua_hr_reports.hr_report_headcount_company_rule',
        'l10n_ua_hr_reports.hr_report_d5_company_rule',
        'l10n_ua_hr_reports.hr_report_wage_fund_company_rule',
    ]

    def test_rules_exist_and_global(self):
        for xmlid in self.RULE_XMLIDS:
            rule = self.env.ref(xmlid)
            self.assertEqual(rule._name, 'ir.access')
            self.assertEqual(
                rule.kind, 'restriction',
                "Rule %s must be a restriction" % xmlid,
            )
