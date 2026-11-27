"""#722: авансовий звіт бухгалтером без HR-прав, коли стоять кадрові модулі УА.

Сценарій #700 з l10n_ua_accounting, але в базі з l10n_ua_hr_base: його
непублічні поля працівника (РНОКПП, паспорт, військовий облік) не мають
ламати проведення звіту.
"""

from odoo.tests import tagged

from odoo.addons.l10n_ua_accounting.tests import test_advance_report_access as base


@tagged('post_install', '-at_install', 'l10n_ua_hr_business_trip')
class TestAdvanceReportHrAccess(base.TestAdvanceReportAccess):
    # Run the #700 scenario methods inherited from l10n_ua_accounting here.
    allow_inherited_tests_method = True

    def test_hr_base_installed(self):
        self.assertIn('rnokpp', self.env['hr.employee']._fields)
