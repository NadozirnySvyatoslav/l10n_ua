"""Регістр позабалансового обліку (клас 0) за простою системою (#256).

Інструкція про застосування Плану рахунків (наказ Мінфіну № 291): запис на
рахунку класу 0 — лише за дебетом або лише за кредитом, без кореспонденції.
Регістр не створює `account.move`, тож ОСВ (і Форма № 1, що теж читає
`account.move.line`) від нього не залежать.
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_account_base')
class TestOffBalanceRegister(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ Позабаланс Регістр',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.env['account.chart.template'].try_loading(
            'ua_psbo', company=cls.company, install_demo=False)
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id]))

        Account = cls.env['account.account'].with_company(cls.company)

        def account(prefix):
            return Account.search([('code', '=like', f'{prefix}%'),
                                   ('company_ids', 'parent_of', cls.company.id)],
                                  order='code', limit=1)

        cls.acc_rented = account('01')
        cls.acc_forms = account('08')
        cls.acc_cash = account('301')
        cls.acc_payable = account('631')
        assert cls.acc_rented.account_type == 'off_balance'
        cls.lessor = cls.env['res.partner'].create({'name': 'ТОВ Орендодавець'})
        cls.lessor2 = cls.env['res.partner'].create({'name': 'ФОП Другий орендодавець'})
        cls.Move = cls.env['l10n_ua.offbalance.move']

    def _entry(self, day, lines, post=True):
        move = self.Move.create({
            'date': day,
            'company_id': self.company.id,
            'ref': 'Договір оренди № 1',
            'line_ids': [(0, 0, vals) for vals in lines],
        })
        if post:
            move.action_post()
        return move

    def _osv(self, start, end, **kw):
        osv = self.env['l10n_ua.offbalance.osv'].create(dict(
            period_start=start, period_end=end, company_id=self.company.id, **kw))
        osv.action_compute()
        return osv

    def test_one_sided_debit_entry_posts(self):
        """Дт 01 15 000 без кредиту — саме те, чого не дає `account.move`."""
        moves_before = self.env['account.move'].search_count(
            [('company_id', '=', self.company.id)])
        move = self._entry(date(2026, 3, 10), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'partner_id': self.lessor.id, 'name': 'Верстат токарний',
            'quantity': 1, 'amount': 15000.0,
        }])
        self.assertEqual(move.state, 'posted')
        self.assertNotEqual(move.name, '/', 'номер присвоюється при проведенні')
        self.assertEqual(move.line_ids.debit, 15000.0)
        self.assertEqual(move.line_ids.credit, 0.0)
        self.assertEqual(
            self.env['account.move'].search_count([('company_id', '=', self.company.id)]),
            moves_before, 'регістр класу 0 не має породжувати проводок')

    def test_trial_balance_ignores_register(self):
        """Головна ОСВ (і Форма № 1 за нею) рахується з проводок — клас 0 туди не йде."""
        self._entry(date(2026, 3, 10), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'partner_id': self.lessor.id, 'name': 'Верстат', 'amount': 15000.0,
        }])
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.company.id)], limit=1)
        bal = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': date(2026, 3, 11),
            'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'account_id': self.acc_cash.id, 'debit': 700.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.acc_payable.id, 'debit': 0.0, 'credit': 700.0}),
            ],
        })
        bal.action_post()

        osv = self.env['l10n_ua.osv'].create({
            'period_start': date(2026, 1, 1), 'period_end': date(2026, 12, 31),
            'company_id': self.company.id,
        })
        osv.action_compute()
        self.assertNotIn(self.acc_rented, osv.line_ids.account_id)
        self.assertFalse(osv.line_ids.filtered(
            lambda l: l.account_id.account_type == 'off_balance'))
        self.assertAlmostEqual(sum(osv.line_ids.mapped('turnover_debit')), 700.0)
        self.assertAlmostEqual(sum(osv.line_ids.mapped('turnover_credit')), 700.0)

    def test_offbalance_osv_opening_turnover_closing(self):
        self._entry(date(2026, 1, 15), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'partner_id': self.lessor.id, 'name': 'Верстати', 'quantity': 3,
            'amount': 30000.0,
        }])
        self._entry(date(2026, 2, 5), [
            {'account_id': self.acc_rented.id, 'direction': 'credit',
             'partner_id': self.lessor.id, 'name': 'Повернення верстата',
             'quantity': 1, 'amount': 10000.0},
            {'account_id': self.acc_rented.id, 'direction': 'debit',
             'partner_id': self.lessor2.id, 'name': 'Ноутбук', 'quantity': 1,
             'amount': 4000.0},
        ])
        # Чернетка у звіт не потрапляє.
        self._entry(date(2026, 2, 6), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'name': 'Чернетка', 'amount': 999.0,
        }], post=False)

        osv = self._osv(date(2026, 2, 1), date(2026, 2, 28))
        line = osv.line_ids.filtered(lambda l: l.account_id == self.acc_rented)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.opening_debit, 30000.0)
        self.assertAlmostEqual(line.turnover_debit, 4000.0)
        self.assertAlmostEqual(line.turnover_credit, 10000.0)
        self.assertAlmostEqual(line.closing_debit, 24000.0)
        self.assertAlmostEqual(line.opening_qty, 3)
        self.assertAlmostEqual(line.quantity_in, 1)
        self.assertAlmostEqual(line.quantity_out, 1)
        self.assertAlmostEqual(line.closing_qty, 3)

        by_partner = self._osv(date(2026, 2, 1), date(2026, 2, 28), by_partner=True)
        closing = {l.partner_id: l.closing_debit for l in by_partner.line_ids}
        self.assertAlmostEqual(closing[self.lessor], 20000.0)
        self.assertAlmostEqual(closing[self.lessor2], 4000.0)

    def test_quantity_only_line(self):
        """Бланки суворого обліку часто ведуть у штуках без вартості."""
        self._entry(date(2026, 4, 1), [{
            'account_id': self.acc_forms.id, 'direction': 'debit',
            'name': 'Трудові книжки', 'quantity': 50,
        }])
        line = self._osv(date(2026, 4, 1), date(2026, 4, 30)).line_ids
        self.assertEqual(line.account_id, self.acc_forms)
        self.assertAlmostEqual(line.closing_qty, 50)

    def test_balance_sheet_account_rejected(self):
        with self.assertRaises(ValidationError):
            self._entry(date(2026, 3, 1), [{
                'account_id': self.acc_cash.id, 'direction': 'debit',
                'name': 'Каса', 'amount': 100.0,
            }], post=False)

    def test_empty_line_rejected(self):
        with self.assertRaises(ValidationError):
            self._entry(date(2026, 3, 1), [{
                'account_id': self.acc_rented.id, 'direction': 'debit',
                'name': 'Нічого',
            }], post=False)

    def test_posted_entry_is_immutable(self):
        move = self._entry(date(2026, 3, 1), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'name': 'Верстат', 'amount': 100.0,
        }])
        with self.assertRaises(UserError):
            move.write({'date': date(2026, 3, 2)})
        with self.assertRaises(UserError):
            move.line_ids.write({'amount': 1.0})
        with self.assertRaises(UserError):
            move.unlink()
        move.action_draft()
        move.line_ids.write({'amount': 1.0})
        self.assertEqual(move.line_ids.debit, 1.0)
        number = move.name
        move.action_post()
        self.assertEqual(move.name, number, 'повторне проведення не міняє номер')

    def test_lock_date_blocks_posting(self):
        self.company.fiscalyear_lock_date = date(2026, 3, 31)
        move = self._entry(date(2026, 3, 1), [{
            'account_id': self.acc_rented.id, 'direction': 'debit',
            'name': 'Верстат', 'amount': 100.0,
        }], post=False)
        with self.assertRaises(UserError):
            move.action_post()

    def test_core_balance_check_untouched(self):
        """Ядро не послаблено: одностороння `account.move` на клас 0 і далі неможлива."""
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.company.id)], limit=1)
        with self.assertRaises(UserError):
            self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': journal.id,
                'company_id': self.company.id,
                'line_ids': [(0, 0, {'account_id': self.acc_rented.id,
                                     'debit': 15000.0, 'credit': 0.0})],
            })
