"""Вид субконто — Selection замість ir.model (#701, ADR 0005).

- UA User і головбух відкривають види субконто без права читати ir.model;
- головбух створює вид лише з моделлю із переліку _selection_subconto_models;
- довільна модель (res.users) не проходить.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSubcontoTypeSelection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ua_user = new_test_user(
            cls.env, login='subc_ua_user', groups='l10n_ua_account_base.group_ua_user')
        cls.ua_manager = new_test_user(
            cls.env, login='subc_ua_manager',
            groups='base.group_user,l10n_ua_account_base.group_ua_manager')
        cls.partner_type = cls.env.ref('l10n_ua_account_base.subconto_type_partner')

    def test_base_models_in_selection(self):
        models = dict(self.env['l10n_ua.subconto.type']._selection_subconto_models())
        for name in ('res.partner', 'res.partner.bank', 'account.account',
                     'account.journal', 'product.product'):
            self.assertIn(name, models)
        self.assertNotIn('res.users', models)

    def test_user_reads_without_ir_model_access(self):
        # На 20.0 головбух має read на ir.model з ядра (#704), UA User — ні
        self.assertFalse(
            self.env['ir.model'].with_user(self.ua_user).has_access('read'),
            'тест має сенс лише без права читати ir.model')
        for user in (self.ua_user, self.ua_manager):
            with self.subTest(user=user.login):
                rec = self.partner_type.with_user(user)
                rec.invalidate_recordset()
                self.assertEqual(rec.model_name, 'res.partner')
                field = rec.fields_get(['model_name'])['model_name']
                self.assertIn('res.partner', dict(field['selection']))

    def test_manager_creates_type_from_list(self):
        rec = self.env['l10n_ua.subconto.type'].with_user(self.ua_manager).create({
            'name': 'Журнали 2', 'code': 'JOURNAL_701', 'model_name': 'account.journal',
        })
        self.assertEqual(rec.model_name, 'account.journal')

    def test_arbitrary_model_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['l10n_ua.subconto.type'].create({
                'name': 'Users', 'code': 'USERS_701', 'model_name': 'res.users',
            })
