"""План рахунків за Наказом № 291 (#145): субрахунки, назви, аналітика, субконто.

Як і `test_offbalance_accounts`, тест піднімає окрему компанію і вантажить на
неї `ua_psbo` явно: у чистій тестовій базі компанія лишається на
`generic_coa`.
"""
from odoo.tests import TransactionCase, tagged

from ..hooks import ensure_psbo_chart
from ..models.template_ua_psbo import (
    PSBO_EXTRA_ACCOUNTS,
    PSBO_RENAMES,
    stock_account_analytics,
)


def _codes(*ranges):
    out = []
    for item in ranges:
        if isinstance(item, tuple):
            out += [str(i) for i in range(item[0], item[1] + 1)]
        else:
            out.append(item)
    return out


# Усі субрахунки Інструкції про застосування Плану рахунків (z0893-99,
# ред. 23.12.2025) — 272 коди. Синтетичні рахунки без субрахунків (17, 22, 39,
# 43, 84, 91…) Інструкція наводить окремо, вони є в стоковому плані.
INSTRUCTION_SUBACCOUNTS = _codes(
    (100, 109), (111, 117), (121, 125), '127', (131, 135), (141, 143),
    (151, 155), (161, 166), (181, 184), '191', '193',
    (201, 209), (211, 213), (281, 286),
    '301', '302', '308', '309', (311, 316), (331, 335), '341', '342', '351', '352',
    (361, 364), (371, 379),
    (401, 404), (411, 414), (421, 425), (441, 443), (451, 453), (471, 478),
    (481, 484), (491, 496),
    (501, 506), '511', '512', (521, 523), '531', '532',
    (601, 606), '611', '612', '621', '622', (631, 633), (641, 644),
    '651', '652', '654', '655', (661, 663), (671, 676), (680, 686),
    (701, 707), (710, 719), (721, 723), (731, 733), (740, 742), (744, 746),
    (791, 793),
    (801, 809), (811, 816), '821', '824', (831, 833),
    (901, 904), (940, 949), '951', '952', (961, 963), (970, 972), (974, 977),
    '021', '022', '023', '024', '025', '041', '042', '071', '072',
)


@tagged('post_install', '-at_install', 'l10n_ua_account_base')
class TestPsboChart(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ План 291 Тест',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.env['account.chart.template'].try_loading(
            'ua_psbo', company=cls.company, install_demo=False)
        cls.env.user.company_ids |= cls.company
        cls.code_digits = int(
            cls.env['account.chart.template']._get_chart_template_data('ua_psbo')
            ['template_data'].get('code_digits') or 6)
        cls.partner_type = cls.env.ref('l10n_ua_account_base.subconto_type_partner')
        cls.product_type = cls.env.ref('l10n_ua_account_base.subconto_type_product')

    @classmethod
    def _padded(cls, code):
        return code.ljust(cls.code_digits, '0')

    def _account(self, code):
        return self.env['account.account'].with_company(self.company).search([
            ('code', '=', self._padded(code)),
            ('company_ids', 'parent_of', self.company.id),
        ])

    def test_instruction_list_is_complete(self):
        self.assertEqual(len(INSTRUCTION_SUBACCOUNTS), 272)
        self.assertEqual(len(set(INSTRUCTION_SUBACCOUNTS)), 272)

    def test_every_instruction_subaccount_is_in_chart(self):
        """Кожен субрахунок Інструкції — рахунок плану або префікс його рахунків.

        Стоковий план розщеплює частину субрахунків глибше (641 → 6411…6416),
        звіти рахують за префіксами, тож розщеплення теж рахується.
        """
        codes = self.env['account.account'].with_company(self.company).search([
            ('company_ids', 'parent_of', self.company.id),
        ]).mapped('code')
        missing = [sub for sub in INSTRUCTION_SUBACCOUNTS
                   if not any(code.startswith(sub) for code in codes)]
        self.assertFalse(missing, f'у плані бракує субрахунків Інструкції: {missing}')

    def test_extra_accounts_types(self):
        for code, _name, account_type, reconcile, analytics in PSBO_EXTRA_ACCOUNTS:
            account = self._account(code)
            self.assertEqual(len(account), 1, f'рахунок {code} не створено')
            self.assertEqual(account.account_type, account_type, code)
            self.assertEqual(account.reconcile, reconcile, code)
            self.assertEqual(account.ua_analytics_type, analytics, code)
        self.assertEqual(self._account('021').ua_class, '0')
        self.assertEqual(self._account('706').ua_class, '7')

    def test_template_only_touches_existing_stock_accounts(self):
        """Аналітика й назви йдуть на стокові xmlid — вони мають існувати.

        Інакше шаблон створив би «рахунок» лише з аналітикою і без коду.
        """
        stock = self.env['account.chart.template']._get_chart_template_model_data(
            'ua_psbo', 'account.account')
        for code in [*stock_account_analytics(), *PSBO_RENAMES]:
            self.assertIn('account_type', stock.get(f'ua_psbp_{code}', {}),
                          f'стокового рахунку {code} немає в шаблоні')

    def test_analytics(self):
        self.assertEqual(self._account('631').ua_analytics_type, 'partner')
        self.assertEqual(self._account('361').ua_analytics_type, 'partner')
        self.assertEqual(self._account('6851').ua_analytics_type, 'partner')
        self.assertEqual(self._account('661').ua_analytics_type, 'employee')
        self.assertEqual(self._account('3721').ua_analytics_type, 'employee')
        goods = self._account('281')
        self.assertEqual(goods.ua_analytics_type, 'product')
        self.assertTrue(goods.ua_is_quantity)
        self.assertTrue(self._account('312').ua_is_currency)
        self.assertTrue(self._account('632').ua_is_currency)
        self.assertFalse(self._account('311').ua_is_currency)

    def test_renamed_accounts(self):
        if not self.env['res.lang']._lang_get('uk_UA'):
            self.skipTest('uk_UA не встановлено')
        account = self._account('475').with_context(lang='uk_UA')
        self.assertEqual(account.name, PSBO_RENAMES['475'])

    def test_subconto_configured_and_optional(self):
        for code, subconto_type in (('631', self.partner_type),
                                    ('361', self.partner_type),
                                    ('201', self.product_type)):
            config = self._account(code).subconto_ids
            self.assertEqual(config.subconto_type_id, subconto_type, code)
            self.assertFalse(config.required,
                             f'субконто на {code} не має бути обовʼязковим')
        self.assertFalse(self._account('661').subconto_ids,
                         'працівників веде bridge-модуль з hr')

    def test_entry_without_subconto_still_posts(self):
        """Субконто на 631 не заважає звичайній проводці без нього."""
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.company.id)], limit=1)
        partner = self.env['res.partner'].create({'name': 'Постачальник 291'})
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': self._account('201').id, 'name': 'матеріали',
                        'debit': 1200.0}),
                (0, 0, {'account_id': self._account('631').id, 'name': 'постачальник',
                        'partner_id': partner.id, 'credit': 1200.0}),
            ],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_hook_backfills_existing_company(self):
        self._account('673').unlink()
        self._account('686').unlink()
        suppliers = self._account('631')
        suppliers.subconto_ids.unlink()
        suppliers.ua_analytics_type = 'none'
        lottery = self._account('475')
        lottery.name = 'Своя назва бухгалтера'

        ensure_psbo_chart(self.env)
        ensure_psbo_chart(self.env)

        self.assertEqual(len(self._account('673')), 1)
        self.assertEqual(self._account('686').account_type, 'liability_current')
        self.assertEqual(suppliers.ua_analytics_type, 'partner')
        self.assertEqual(len(suppliers.subconto_ids), 1)
        self.assertEqual(lottery.name, 'Своя назва бухгалтера',
                         'хук не переписує назв наявних рахунків')
        self.assertEqual(len(self._account('021')), 1,
                         'повторний запуск хука не дублює рахунки')

    def test_hook_respects_manual_analytics(self):
        account = self._account('631')
        account.ua_analytics_type = 'contract'
        ensure_psbo_chart(self.env)
        self.assertEqual(account.ua_analytics_type, 'contract')
