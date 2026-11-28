"""Вид субконто — Selection замість ir.model (#701, ADR 0005).

- UA User і головбух відкривають види субконто без права читати ir.model;
- головбух створює вид лише з моделлю із переліку _selection_subconto_models;
- довільна модель (res.users) не проходить;
- вид із моделлю поза переліком, що лишився після оновлення, проводиться.
"""

import importlib.util
import os

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
        for user in (self.ua_user, self.ua_manager):
            with self.subTest(user=user.login):
                self.assertFalse(
                    self.env['ir.model'].with_user(user).has_access('read'),
                    'тест має сенс лише без права читати ir.model')
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

    def _legacy_type(self):
        """Вид, створений користувачем до 19.0.1.5.0 з моделлю поза переліком.

        До PR model_id міг вказувати на будь-яку модель; після оновлення
        значення лишається в колонці model_name. Створюємо з дозволеною
        моделлю й переводимо SQL-ем — так, як його лишає оновлення.
        """
        stype = self.env['l10n_ua.subconto.type'].create({
            'name': 'Валюта (старий вид)', 'code': 'CUR_LEGACY_701',
            'model_name': 'account.journal',
        })
        self.env.cr.execute(
            "UPDATE l10n_ua_subconto_type SET model_name = 'res.currency' WHERE id = %s",
            [stype.id])
        stype.invalidate_recordset()
        return stype

    def test_legacy_type_outside_list_still_posts(self):
        """Оновлення бази з кастомним видом не ламає проведення (#706, pr-review 28.11)."""
        stype = self._legacy_type()
        self.assertEqual(stype.model_name, 'res.currency')
        account = self.env['account.account'].create({
            'code': '949701', 'name': 'Legacy subconto 701', 'account_type': 'expense'})
        cash = self.env['account.account'].create({
            'code': '301701', 'name': 'Cash 701', 'account_type': 'asset_cash'})
        journal = self.env['account.journal'].create({
            'name': 'Legacy 701', 'code': 'LG701', 'type': 'general'})
        self.env['l10n_ua.account.subconto'].create({
            'account_id': account.id, 'subconto_type_id': stype.id, 'required': True})
        uah = self.env.ref('base.UAH')

        move = self.env['account.move'].create({
            'journal_id': journal.id, 'move_type': 'entry',
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': 100, 'subconto_ids': [
                    (0, 0, {'subconto_type_id': stype.id, 'res_id': uah.id})]}),
                (0, 0, {'account_id': cash.id, 'credit': 100}),
            ]})
        move.action_post()

        self.assertEqual(move.state, 'posted')
        sub = move.line_ids.subconto_ids
        self.assertEqual(sub.res_model, 'res.currency')
        self.assertEqual(sub.display_name, uah.name)
        # Обов'язкове субконто старого виду й далі перевіряється
        with self.assertRaises(ValidationError):
            self.env['account.move'].create({
                'journal_id': journal.id, 'move_type': 'entry',
                'line_ids': [
                    (0, 0, {'account_id': account.id, 'debit': 50}),
                    (0, 0, {'account_id': cash.id, 'credit': 50}),
                ]})
        # Інші поля виду редагуються; модель — лише на значення з переліку
        stype.name = 'Валюта (перейменовано)'
        with self.assertRaises(ValidationError):
            stype.model_name = 'res.users'

    def test_pre_migration_warns_about_legacy_type(self):
        stype = self._legacy_type()
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'migrations', '19.0.1.5.0', 'pre-migration.py')
        spec = importlib.util.spec_from_file_location('l10n_ua_account_base_pre_1_5', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        logger = 'l10n_ua_account_base_pre_1_5'
        with self.assertLogs(logger, level='WARNING') as logs:
            module.migrate(self.env.cr, '19.0.1.4.0')
        legacy = [line for line in logs.output if 'CUR_LEGACY_701' in line]
        self.assertEqual(len(legacy), 1, logs.output)
        self.assertIn('res.currency', legacy[0])
        # Види з даних модуля (Контрагенти тощо) не звіряються
        self.assertFalse([line for line in logs.output if 'PARTNER' in line], logs.output)
