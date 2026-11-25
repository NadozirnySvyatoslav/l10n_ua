"""ОСВ з розгорткою по контрагентах (#588, п. 2).

Синтетична ОСВ з прапорцем «Розгорнути по контрагентах»: рахунки з
аналітикою по контрагентах/працівниках (``ua_analytics_type`` partner /
employee) отримують рядок рахунку з розгорнутим сальдо (Дт і Кт окремо) і
рядки-розгортку по кожному контрагенту; решта рахунків і ОСВ без прапорця —
як і раніше.
"""

from datetime import date

from odoo.tests import TransactionCase, tagged

MONEY = ('opening_debit', 'opening_credit', 'turnover_debit',
         'turnover_credit', 'closing_debit', 'closing_credit')


@tagged('post_install', '-at_install')
class TestOsvExpand(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'ОСВ розгортка',
            'code': 'OSVX',
            'type': 'general',
            'company_id': cls.company.id,
        })

        def account(code, name, account_type, analytics='none'):
            return cls.env['account.account'].create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'ua_analytics_type': analytics,
                'company_ids': [(4, cls.company.id)],
            })

        # 361-подібний: розрахунки з контрагентами.
        cls.acc_settle = account('OSVX361', 'ОСВ розрахунки', 'asset_current', 'partner')
        # 661-подібний: розрахунки з працівниками.
        cls.acc_wages = account('OSVX661', 'ОСВ оплата праці', 'liability_current', 'employee')
        # Без аналітики: витрати / банк.
        cls.acc_plain = account('OSVX91', 'ОСВ витрати', 'expense')
        cls.acc_bank = account('OSVX311', 'ОСВ банк', 'asset_current')

        Partner = cls.env['res.partner']
        cls.buyer = Partner.create({'name': 'ОСВХ Покупець'})
        cls.supplier = Partner.create({'name': 'ОСВХ Постачальник'})
        cls.employees = Partner.create([
            {'name': 'ОСВХ Працівник 1'},
            {'name': 'ОСВХ Працівник 2'},
            {'name': 'ОСВХ Працівник 3'},
        ])

    def _post(self, move_date, debit_acc, credit_acc, amount,
              debit_partner=None, credit_partner=None):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id,
                    'partner_id': debit_partner.id if debit_partner else False,
                    'debit': amount,
                }),
                (0, 0, {
                    'account_id': credit_acc.id,
                    'partner_id': credit_partner.id if credit_partner else False,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _osv(self, expand=True, osv_type='synthetic'):
        osv = self.env['l10n_ua.osv'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'osv_type': osv_type,
            'expand_partners': expand,
            'company_id': self.company.id,
        })
        osv.action_compute()
        return osv

    def _summary(self, osv, account):
        return osv.line_ids.filtered(
            lambda l: l.account_id == account and not l.is_detail)

    def _details(self, osv, account):
        return osv.line_ids.filtered(
            lambda l: l.account_id == account and l.is_detail)

    def _assert_vals(self, line, **expected):
        self.assertEqual(len(line), 1)
        for field in MONEY:
            self.assertAlmostEqual(
                line[field], expected.get(field, 0.0),
                msg=f'{line.account_id.code} {line.partner_id.name or "—"}: {field}')

    def _settlement_data(self):
        # Покупець винен 1000 (Дт сальдо), постачальнику передплатили — ні:
        # постачальник має Кт сальдо 300 на тому ж рахунку.
        self._post(date(2024, 12, 20), self.acc_settle, self.acc_plain, 1000.0,
                   debit_partner=self.buyer)
        self._post(date(2024, 12, 21), self.acc_plain, self.acc_settle, 300.0,
                   credit_partner=self.supplier)
        # У періоді: покупець сплатив 400, постачальнику ще нараховано 200.
        self._post(date(2025, 1, 10), self.acc_bank, self.acc_settle, 400.0,
                   credit_partner=self.buyer)
        self._post(date(2025, 1, 15), self.acc_plain, self.acc_settle, 200.0,
                   credit_partner=self.supplier)

    def test_expanded_balance_debit_and_credit_separately(self):
        """Критерій 3: розгорнуте сальдо Дт і Кт; рядок рахунку = сума розгортки."""
        self._settlement_data()
        osv = self._osv()

        self._assert_vals(
            self._summary(osv, self.acc_settle),
            opening_debit=1000.0, opening_credit=300.0,
            turnover_credit=600.0,
            closing_debit=600.0, closing_credit=500.0)

        details = self._details(osv, self.acc_settle)
        self.assertEqual(details.partner_id, self.buyer | self.supplier)
        self._assert_vals(
            details.filtered(lambda l: l.partner_id == self.buyer),
            opening_debit=1000.0, turnover_credit=400.0, closing_debit=600.0)
        self._assert_vals(
            details.filtered(lambda l: l.partner_id == self.supplier),
            opening_credit=300.0, turnover_credit=200.0, closing_credit=500.0)

        summary = self._summary(osv, self.acc_settle)
        for field in MONEY:
            self.assertAlmostEqual(summary[field], sum(details.mapped(field)), msg=field)

    def test_without_expand_numbers_unchanged(self):
        """Критерій 5: без прапорця — згорнуте сальдо і жодної розгортки."""
        self._settlement_data()
        osv = self._osv(expand=False)

        self.assertFalse(osv.line_ids.filtered('is_detail'))
        self._assert_vals(
            self._summary(osv, self.acc_settle),
            opening_debit=700.0, turnover_credit=600.0, closing_debit=100.0)

    def test_accounts_without_analytics_not_expanded(self):
        """Рахунки без аналітики контрагента — один рядок, як у синтетичній ОСВ."""
        self._settlement_data()
        expanded = self._osv()
        plain = self._osv(expand=False)

        for account in (self.acc_plain, self.acc_bank):
            self.assertFalse(self._details(expanded, account))
            line = self._summary(expanded, account)
            self._assert_vals(line, **{
                f: self._summary(plain, account)[f] for f in MONEY})

        # Подвійний запис: обороти рядків рахунків (без розгортки) зведені.
        summary = expanded.summary_line_ids
        self.assertAlmostEqual(sum(summary.mapped('turnover_debit')),
                               sum(summary.mapped('turnover_credit')))

    def test_wages_by_employee_and_zero_after_payment(self):
        """Критерій 2: 661 по працівниках; після виплати сальдо кожного 0."""
        for employee, amount in zip(self.employees, (10000.0, 12000.0, 8000.0)):
            self._post(date(2025, 1, 31), self.acc_plain, self.acc_wages, amount,
                       credit_partner=employee)

        osv = self._osv()
        details = self._details(osv, self.acc_wages)
        self.assertEqual(details.partner_id, self.employees)
        self.assertEqual(
            sorted(details.mapped('closing_credit')), [8000.0, 10000.0, 12000.0])
        self._assert_vals(self._summary(osv, self.acc_wages),
                          turnover_credit=30000.0, closing_credit=30000.0)

        for employee, amount in zip(self.employees, (10000.0, 12000.0, 8000.0)):
            self._post(date(2025, 1, 31), self.acc_wages, self.acc_bank, amount,
                       debit_partner=employee)
        osv.action_compute()

        details = self._details(osv, self.acc_wages)
        self.assertEqual(len(details), 3)
        for line in details:
            self.assertAlmostEqual(line.closing_debit, 0.0)
            self.assertAlmostEqual(line.closing_credit, 0.0)
        self._assert_vals(self._summary(osv, self.acc_wages),
                          turnover_debit=30000.0, turnover_credit=30000.0)

    def test_lines_without_partner_get_own_row(self):
        """Старі проводки без партнера на 661 — окремий рядок з порожнім партнером."""
        self._post(date(2025, 1, 31), self.acc_plain, self.acc_wages, 500.0)
        self._post(date(2025, 1, 31), self.acc_plain, self.acc_wages, 700.0,
                   credit_partner=self.employees[0])

        details = self._details(self._osv(), self.acc_wages)
        self.assertEqual(len(details), 2)
        self.assertAlmostEqual(
            details.filtered(lambda l: not l.partner_id).closing_credit, 500.0)

    def test_order_views_and_export_action(self):
        """Рядок рахунку йде перед розгорткою; поля форми і дія списку."""
        self._settlement_data()
        osv = self._osv()

        settle = osv.line_ids.filtered(lambda l: l.account_id == self.acc_settle)
        self.assertEqual(settle.mapped('is_detail'), [False, True, True])
        self.assertFalse(osv.summary_line_ids.filtered('is_detail'))
        self.assertTrue(all(osv.detail_line_ids.mapped('is_detail')))
        self.assertEqual(osv.summary_line_ids | osv.detail_line_ids, osv.line_ids)

        action = osv.action_open_lines()
        self.assertEqual(action['res_model'], 'l10n_ua.osv.line')
        self.assertEqual(
            self.env['l10n_ua.osv.line'].search(action['domain']), osv.line_ids)

    def test_flag_ignored_for_analytic_type(self):
        """Прапорець діє лише на синтетичну ОСВ; аналітична — як і раніше."""
        self._settlement_data()
        osv = self._osv(osv_type='analytic')
        self.assertFalse(osv.line_ids.filtered('is_detail'))
        self.assertEqual(
            self._summary(osv, self.acc_settle).partner_id, self.buyer | self.supplier)
