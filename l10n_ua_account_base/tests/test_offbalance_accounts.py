"""Клас 0 «Позабалансові рахунки» має доїжджати разом зі стоковим планом ua_psbo.

Тест піднімає окрему компанію і вантажить на неї план явно: у чистій тестовій
базі компанія лишається на `generic_coa`, тож без цього перевірялося б що
завгодно, тільки не український план.
"""
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import TransactionCase, tagged

from ..models.template_ua_psbo import OFFBALANCE_ACCOUNTS


@tagged('post_install', '-at_install', 'l10n_ua_account_base')
class TestOffBalanceAccounts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ Позабаланс Тест',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.env['account.chart.template'].try_loading(
            'ua_psbo', company=cls.company, install_demo=False)
        cls.env.user.company_ids |= cls.company

        # Odoo доповнює коди нулями до `code_digits` плану (для ua_psbo це 6),
        # тож рахунок 01 живе в базі як 010000 — рівно як стоковий 631 як
        # 631000. Ширину беремо з самого плану: зашита константа розійшлася б
        # із ним мовчки, і тест перевіряв би неіснуючі коди.
        cls.code_digits = int(
            cls.env['account.chart.template']._get_chart_template_data('ua_psbo')
            ['template_data'].get('code_digits') or 6)
        cls.offbalance_codes = sorted(cls._padded(code)
                                      for code, _name, _analytics in OFFBALANCE_ACCOUNTS)
        cls.partner_analytics_codes = [cls._padded(code)
                                       for code, _name, analytics in OFFBALANCE_ACCOUNTS
                                       if analytics == 'partner']

    @classmethod
    def _padded(cls, code):
        return code.ljust(cls.code_digits, '0')

    def _accounts(self, codes):
        return self.env['account.account'].with_company(self.company).search(
            [('code', 'in', codes),
             ('company_ids', 'parent_of', self.company.id)])

    def test_all_nine_offbalance_accounts_loaded(self):
        found = self._accounts(self.offbalance_codes)
        self.assertEqual(
            sorted(found.mapped('code')), self.offbalance_codes,
            'план має містити всі 9 позабалансових рахунків Наказу № 291')

    def test_offbalance_accounts_have_correct_type(self):
        accounts = self._accounts(self.offbalance_codes)
        self.assertTrue(accounts)
        for account in accounts:
            self.assertEqual(account.account_type, 'off_balance',
                              f'рахунок {account.code} має бути позабалансовим')
            self.assertFalse(account.reconcile,
                              f'рахунок {account.code} не звіряється')
            self.assertEqual(account.ua_class, '0')

    def test_stock_chart_is_not_replaced(self):
        """Наш шаблон додає рахунки, а не заміщує стокові 332.

        Перевіряємо за конкретними кодами зі стокового `l10n_ua`, а не за
        обчисленим `ua_class`: клас рахується з першої цифри коду, тож на
        generic-плані він дав би ті самі «класи» і тест зеленів би дарма.
        """
        Account = self.env['account.account'].with_company(self.company)
        for prefix in ('631', '661', '311', '281'):
            found = Account.search([('code', '=like', f'{prefix}%'),
                                     ('company_ids', 'parent_of', self.company.id)])
            self.assertTrue(found, f'стоковий рахунок {prefix} зник з плану')

    def test_partner_analytics_where_counterparty_matters(self):
        for account in self._accounts(self.partner_analytics_codes):
            self.assertEqual(account.ua_analytics_type, 'partner',
                              f'рахунок {account.code} має аналітику за контрагентом')

    def test_offbalance_entry_must_still_balance(self):
        """Odoo вимагає балансу навіть на позабалансових рахунках — і це лишається.

        За Наказом № 291 клас 0 ведеться за простою системою (лише Дт або лише
        Кт). Односторонні записи живуть у власному регістрі
        `l10n_ua.offbalance.move` (#256), а `_check_balanced` ядра свідомо не
        послаблено — див. `test_offbalance_register`. Тест фіксує, що
        збалансована проводка на клас 0 як була, так і проводиться.
        """
        rented = self._accounts([self._padded('01')])
        contra = self._accounts([self._padded('09')])
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.company.id)], limit=1)
        self.assertTrue(journal, 'план рахунків має створити загальний журнал')

        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': rented.id, 'name': 'орендоване обладнання',
                        'debit': 15000.0, 'credit': 0.0}),
                (0, 0, {'account_id': contra.id, 'name': 'контрзапис',
                        'debit': 0.0, 'credit': 15000.0}),
            ],
        })
        move.action_post()

        self.assertEqual(move.state, 'posted')

    def test_hook_backfills_existing_company(self):
        """Компанії, яким план дістався до встановлення модуля, добираються хуком.

        Це не теоретичний випадок, а звичайний: шаблон матеріалізується один раз,
        коли на компанію ставиться локалізація, тож у будь-якій наявній базі
        `l10n_ua` стоїть раніше за цей модуль і нових рахунків там не буде.
        """
        from ..hooks import ensure_offbalance_accounts

        self._accounts(self.offbalance_codes).unlink()
        self.assertFalse(self._accounts(self.offbalance_codes))

        ensure_offbalance_accounts(self.env)

        self.assertEqual(sorted(self._accounts(self.offbalance_codes).mapped('code')),
                          self.offbalance_codes)
        self.assertEqual(self._accounts([self._padded('05')]).ua_analytics_type, 'partner')

    def test_migration_ships_for_the_current_version(self):
        """Наявні бази добирає міграція, а не хук — і вона має бути «свіжою».

        `post_init_hook` виконується лише при install, тож для баз, де модуль
        уже стоїть, єдиний шлях — каталог міграції з поточною версією модуля.
        Якщо версію бампнуть, а каталог лишиться зі старим номером, оновлення
        мовчки пройде повз нього — тест ловить саме це розходження.
        """
        version = get_manifest('l10n_ua_account_base')['version']
        migrations = os.path.join(
            get_module_path('l10n_ua_account_base'), 'migrations', version)

        self.assertTrue(
            os.path.isfile(os.path.join(migrations, 'post-migration.py')),
            f'немає migrations/{version}/post-migration.py — наявні бази '
            f'лишаться без класу 0')

    def test_hook_is_idempotent(self):
        from ..hooks import ensure_offbalance_accounts

        ensure_offbalance_accounts(self.env)
        ensure_offbalance_accounts(self.env)

        self.assertEqual(len(self._accounts([self._padded('01')])), 1,
                          'повторний запуск хука не має дублювати рахунки')
