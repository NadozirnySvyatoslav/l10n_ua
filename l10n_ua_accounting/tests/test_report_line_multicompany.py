"""Рядки фінзвітів не видно користувачу іншої компанії (#679).

Заголовки Ф1–Ф4 і спрощеної фінзвітності вже мали правило компанії,
а моделі рядків — ні: користувач компанії Б через search/read бачив
суми рядків звітів компанії А.
"""

from datetime import date

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import AccountingTestCase

LINE_MODELS = {
    'l10n_ua.balance.report': {'date_to': date(2046, 12, 31)},
    'l10n_ua.pnl.report': {'date_from': date(2046, 1, 1), 'date_to': date(2046, 12, 31)},
    'l10n_ua.cashflow.report': {'date_from': date(2046, 1, 1), 'date_to': date(2046, 12, 31)},
    'l10n_ua.equity.report': {'date_from': date(2046, 1, 1), 'date_to': date(2046, 12, 31)},
    'l10n_ua.small.report': {
        'kind': 'small', 'date_from': date(2046, 1, 1), 'date_to': date(2046, 12, 31)},
}


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestReportLineMultiCompany(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({
            'name': 'Компанія Б (#679)', 'country_id': cls.env.ref('base.ua').id})
        groups = [cls.env.ref('base.group_user').id,
                  cls.env.ref('account.group_account_user').id]
        cls.user_b = cls.env['res.users'].create({
            'name': 'Бухгалтер Б', 'login': 'acc_679_user_b',
            'company_id': cls.company_b.id,
            'company_ids': [(6, 0, cls.company_b.ids)],
            'group_ids': [(6, 0, groups)],
        })
        cls.user_a = cls.env['res.users'].create({
            'name': 'Бухгалтер А', 'login': 'acc_679_user_a',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, groups)],
        })
        cls.reports = {}
        for model, vals in LINE_MODELS.items():
            report = cls.env[model].create(dict(vals, company_id=cls.company.id))
            report.action_compute()
            cls.reports[model] = report

    def test_lines_exist(self):
        """Передумова: у кожного звіту компанії А є рядки."""
        for model, report in self.reports.items():
            with self.subTest(model=model):
                self.assertTrue(report.line_ids, '%s: звіт без рядків' % model)

    def test_other_company_user_cannot_search_lines(self):
        """Користувач Б не знаходить рядків звіту компанії А."""
        for model, report in self.reports.items():
            line_model = report.line_ids._name
            with self.subTest(model=line_model):
                count = self.env[line_model].with_user(self.user_b).search_count(
                    [('report_id', '=', report.id)])
                self.assertEqual(count, 0)

    def test_other_company_user_cannot_read_lines(self):
        """Прямий read рядка компанії А для користувача Б — AccessError."""
        for model, report in self.reports.items():
            line = report.line_ids[:1]
            with self.subTest(model=line._name):
                with self.assertRaises(AccessError):
                    line.with_user(self.user_b).read(['report_id'])

    def test_other_company_user_cannot_write_lines(self):
        """Змінити рядок компанії А користувач Б не може."""
        for model, report in self.reports.items():
            line = report.line_ids[:1]
            with self.subTest(model=line._name):
                with self.assertRaises(AccessError):
                    line.with_user(self.user_b).write({'name': 'x'})

    def test_same_company_user_sees_lines(self):
        """Користувач А і далі бачить усі рядки свого звіту."""
        for model, report in self.reports.items():
            line_model = report.line_ids._name
            with self.subTest(model=line_model):
                count = self.env[line_model].with_user(self.user_a).search_count(
                    [('report_id', '=', report.id)])
                self.assertEqual(count, len(report.line_ids))

    def test_rules_exist(self):
        """На кожну модель рядків є обмежувальне правило компанії."""
        for short in ('balance', 'pnl', 'cashflow', 'equity', 'small'):
            xmlid = 'l10n_ua_accounting.l10n_ua_%s_report_line_company_rule' % short
            with self.subTest(xmlid=xmlid):
                self.assertEqual(self.env.ref(xmlid).kind, 'restriction')
