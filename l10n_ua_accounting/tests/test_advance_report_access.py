"""Авансовий звіт бухгалтером без HR-груп — issue #700, ADR 0005.

Бухгалтеру не дають read на hr.employee (персональні дані). Сценарій
перевіряє, що без HR-прав він усе одно створює, погоджує і проводить
авансовий звіт, а партнер працівника потрапляє в проводку 372.
"""

from odoo.exceptions import AccessError
from odoo.tests import Form, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval, time

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestAdvanceReportAccess(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.account_372 = Account.search([('code', '=like', '372%')], limit=1) or Account.create({
            'code': '3721', 'name': 'Розрахунки з підзвітними особами (тест)',
            'account_type': 'asset_current', 'company_ids': [(6, 0, cls.company.ids)]})
        cls.account_92 = Account.create({
            'code': '9201', 'name': 'Адміністративні витрати (тест)',
            'account_type': 'expense', 'company_ids': [(6, 0, cls.company.ids)]})
        cls.company.l10n_ua_advance_journal_id = cls.misc_journal
        cls.employee.work_contact_id = cls.env['res.partner'].create(
            {'name': 'Тестовий працівник (контакт)'})
        cls.employee.job_id = cls.env['hr.job'].create({'name': 'Інженер-727'})
        cls.employee.department_id = cls.env['hr.department'].create(
            {'name': 'Відділ-727', 'company_id': cls.company.id})

        def user(login, group):
            return new_test_user(
                cls.env, login=login, groups=f'base.group_user,{group}',
                company_id=cls.company.id, company_ids=[(6, 0, cls.company.ids)])

        cls.users = [
            user('acc_user_700', 'account.group_account_user'),
            user('ua_acc_700', 'l10n_ua_account_base.group_ua_accountant'),
        ]

    def _scenario(self, accountant):
        self.assertFalse(accountant.has_group('hr.group_hr_user'))
        env = self.env(user=accountant)
        with Form(env['l10n_ua.advance.report']) as form:
            form.employee_id = self.employee.with_env(env)
            form.purpose = 'Відрядження'
            form.advance_amount = 2000.0
            with form.line_ids.new() as line:
                line.description = 'Таксі'
                line.expense_type = 'transport'
                line.amount = 1500.0
                line.account_id = self.account_92.with_env(env)
        report = form.record
        report.action_submit()
        report.action_approve()
        report.action_post()
        report.invalidate_recordset()
        self.assertEqual(report.state, 'posted')
        credit = report.move_id.line_ids.filtered(
            lambda l: l.account_id == self.account_372)
        self.assertEqual(credit.partner_id, self.employee.work_contact_id)
        self.assertTrue(report.employee_id.display_name)
        return report

    def test_accountant_without_hr_posts_report(self):
        for accountant in self.users:
            with self.subTest(login=accountant.login):
                self._scenario(accountant)

    def test_accountant_cannot_read_private_employee_fields(self):
        for accountant in self.users:
            employee = self.employee.with_user(accountant)
            employee.invalidate_recordset()
            with self.subTest(login=accountant.login), self.assertRaises(AccessError):
                employee.read(['private_phone'])

    def test_accountant_without_hr_prints_report(self):
        """#727: друк звіту бухгалтером без HR-прав — ПІБ, посада, відділ."""
        action = self.env.ref('l10n_ua_accounting.action_report_advance_report')
        for accountant in self.users:
            with self.subTest(login=accountant.login):
                report = self._scenario(accountant)
                env = self.env(user=accountant)
                html, _type = env['ir.actions.report']._render_qweb_html(
                    action.report_name, report.ids)
                html = html.decode()
                self.assertIn('Тестовий працівник', html)
                self.assertIn('Інженер-727', html)
                self.assertIn('Відділ-727', html)
                # file name of the download (report controller)
                name = safe_eval(action.with_env(env).print_report_name,
                                 {'object': report.with_env(env), 'time': time})
                self.assertIn('Тестовий працівник', name)
