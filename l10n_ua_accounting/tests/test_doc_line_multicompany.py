"""Рядки документів не видно користувачу іншої компанії (#685).

Авансовий звіт, закриття періоду, переоцінка валюти й акт наданих послуг
мали правило компанії на документі, а моделі рядків — ні: користувач
компанії Б знаходив, читав, змінював і видаляв рядки документів компанії А,
а також додавав рядок у документ А.
"""

from datetime import date

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestDocLineMultiCompany(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({
            'name': 'Компанія Б (#685)', 'country_id': cls.env.ref('base.ua').id})
        groups = [cls.env.ref('base.group_user').id,
                  cls.env.ref('account.group_account_user').id]

        def user(login, companies):
            return cls.env['res.users'].create({
                'name': login, 'login': login,
                'company_id': companies[0].id,
                'company_ids': [(6, 0, [c.id for c in companies])],
                'group_ids': [(6, 0, groups)],
            })
        cls.user_a = user('acc_685_a', cls.company)
        cls.user_b = user('acc_685_b', cls.company_b)
        cls.user_ab = user('acc_685_ab', cls.company | cls.company_b)

        account = cls.env['account.account'].search(
            [('company_ids', 'in', cls.company.id)], limit=1)
        company = cls.company.id
        currency = cls.company.currency_id.id
        period = cls.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(2047, 1, 1),
            'date_end': date(2047, 1, 31),
            'company_id': company,
        })
        # модель рядка -> (поле на документ, документ А, значення нового рядка)
        advance = cls.env['l10n_ua.advance.report'].create({
            'name': 'АЗ-685', 'date': date(2047, 1, 31),
            'employee_id': cls.employee.id, 'company_id': company,
            'currency_id': currency, 'purpose': 'Відрядження',
            'line_ids': [(0, 0, {'date': date(2047, 1, 20), 'description': 'Квиток',
                                 'amount': 100})],
        })
        closing = cls.env['l10n_ua.period.closing'].create({
            'period_id': period.id, 'company_id': company,
            'journal_id': cls.misc_journal.id, 'lock_period': False,
            'closing_line_ids': [(0, 0, {'account_id': account.id, 'debit': 100})],
        })
        reval = cls.env['l10n_ua.currency.revaluation'].create({
            'date': date(2047, 1, 31), 'company_id': company,
            'line_ids': [(0, 0, {'account_id': account.id})],
        })
        act = cls.env['l10n_ua.service.act'].create({
            'name': 'АКТ-685', 'date': date(2047, 1, 31),
            'partner_id': cls.partner.id, 'company_id': company,
            'currency_id': currency,
            'line_ids': [(0, 0, {'name': 'Консультація', 'quantity': 1,
                                 'price_unit': 100})],
        })
        cls.cases = {
            'l10n_ua.advance.report.line': (
                'report_id', advance, advance.line_ids,
                {'date': date(2047, 1, 21), 'description': 'x', 'amount': 1}),
            'l10n_ua.period.closing.line': (
                'closing_id', closing, closing.closing_line_ids,
                {'account_id': account.id}),
            'l10n_ua.currency.revaluation.line': (
                'revaluation_id', reval, reval.line_ids,
                {'account_id': account.id}),
            'l10n_ua.service.act.line': (
                'act_id', act, act.line_ids,
                {'name': 'x', 'quantity': 1, 'price_unit': 1}),
        }

    def test_lines_exist(self):
        """Передумова: у кожного документа компанії А є рядок."""
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                self.assertEqual(len(line), 1)

    def test_other_company_user_cannot_search_lines(self):
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                found = self.env[model].with_user(self.user_b).search([('id', '=', line.id)])
                self.assertFalse(found)

    def test_other_company_user_cannot_read_lines(self):
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    line.with_user(self.user_b).read(['display_name'])

    def test_other_company_user_cannot_write_lines(self):
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    line.with_user(self.user_b).write({'sequence': 99} if 'sequence' in line._fields
                                                      else {'account_id': line.account_id.id})

    def test_other_company_user_cannot_unlink_lines(self):
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    line.with_user(self.user_b).unlink()

    def test_other_company_user_cannot_create_line_into_a(self):
        for model, (field, doc, _line, vals) in self.cases.items():
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    self.env[model].with_user(self.user_b).create(dict(vals, **{field: doc.id}))

    def test_two_company_user_sees_only_selected(self):
        """Користувач А+Б бачить рядок А лише коли вибрана компанія А."""
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                Line = self.env[model].with_user(self.user_ab)
                self.assertFalse(Line.with_context(allowed_company_ids=self.company_b.ids)
                                 .search([('id', '=', line.id)]))
                self.assertEqual(Line.with_context(allowed_company_ids=self.company.ids)
                                 .search([('id', '=', line.id)]), line)

    def test_same_company_user_sees_lines(self):
        for model, (_f, _doc, line, _v) in self.cases.items():
            with self.subTest(model=model):
                found = self.env[model].with_user(self.user_a).search([('id', '=', line.id)])
                self.assertEqual(found, line)

    def test_rules_exist(self):
        for short in ('advance_report', 'period_closing', 'currency_revaluation', 'service_act'):
            xmlid = 'l10n_ua_accounting.l10n_ua_%s_line_company_rule' % short
            with self.subTest(xmlid=xmlid):
                self.assertEqual(self.env.ref(xmlid).kind, 'restriction')
