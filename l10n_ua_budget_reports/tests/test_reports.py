"""Tests for budget reports — render to HTML without errors."""
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_budget_reports')
class TestBudgetReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kekv_2111 = cls.env.ref('l10n_ua_budget_base.kekv_2111')
        cls.kekv_2273 = cls.env.ref('l10n_ua_budget_base.kekv_2273')
        cls.kpkvk = cls.env.ref('l10n_ua_budget_base.kpkvk_2201190_2025')
        cls.estimate = cls.env['l10n_ua.budget.estimate'].create({
            'title': 'TEST estimate for report',
            'year': 2025,
            'fund_type': 'both',
            'kpkvk_id': cls.kpkvk.id,
            'line_ids': [
                Command.create({
                    'kekv_id': cls.kekv_2111.id, 'fund_type': 'general',
                    'm01': 1000, 'm06': 2000, 'm12': 3000,
                }),
                Command.create({
                    'kekv_id': cls.kekv_2273.id, 'fund_type': 'special',
                    'm03': 500, 'm09': 800,
                }),
            ],
        })
        cls.estimate.action_submit()
        cls.estimate.action_approve()

    def test_estimate_pdf_renders(self):
        """The kostorys QWeb template should render to HTML without exceptions."""
        report = self.env.ref('l10n_ua_budget_reports.action_report_budget_estimate')
        html, _content_type = report._render_qweb_html(report.report_name, self.estimate.ids)
        self.assertIn(b'KOSHTORYS' if False else 'КОШТОРИС', html.decode() if isinstance(html, bytes) else html)
        self.assertIn('Загальний фонд', html.decode() if isinstance(html, bytes) else html)
        self.assertIn('Спеціальний фонд', html.decode() if isinstance(html, bytes) else html)

    def test_form_2d_wizard_dates(self):
        wizard = self.env['l10n_ua.budget.form_2d.wizard'].create({
            'estimate_id': self.estimate.id,
            'period': 'q2',
        })
        self.assertEqual(str(wizard.date_from), '2025-04-01')
        self.assertEqual(str(wizard.date_to), '2025-06-30')

    def test_form_2d_wizard_year(self):
        wizard = self.env['l10n_ua.budget.form_2d.wizard'].new({
            'estimate_id': self.estimate.id,
            'period': 'year',
        })
        wizard._compute_dates()
        self.assertEqual(str(wizard.date_from), '2025-01-01')
        self.assertEqual(str(wizard.date_to), '2025-12-31')

    def test_form_2d_report_data(self):
        wizard = self.env['l10n_ua.budget.form_2d.wizard'].create({
            'estimate_id': self.estimate.id,
            'period': 'year',
        })
        rows = wizard.get_report_data()
        # Only 1 general-fund line (КЕКВ 2111), with planned = 6000
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kekv_code'], '2111')
        self.assertEqual(rows[0]['plan'], 6000.0)

    def test_form_2d_plan_follows_the_period(self):
        """Той самий фікс, що й у мультиформі: план за період, а не річний.

        Кошторис: 1000 у січні, 2000 у червні, 3000 у грудні. За II квартал
        план — рівно 2000, тоді як річний дав би 6000 і «% виконання» втричі
        занижений.
        """
        wizard = self.env['l10n_ua.budget.form_2d.wizard'].create({
            'estimate_id': self.estimate.id,
            'period': 'q2',
        })

        rows = wizard.get_report_data()

        self.assertEqual(rows[0]['plan'], 2000.0)

    def test_form_2d_wizard_action_returns_report(self):
        """Wizard's action_print should return a report action dict."""
        # Без макета документа report_action() для адміна повертає не звіт, а
        # майстер налаштування макета (ir_actions_report.py:1179). У бойовій базі
        # макет заданий, у чистій тестовій — ні, тож задаємо його явно, інакше
        # тест перевіряє стан компанії, а не поведінку майстра.
        self.env.company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        wizard = self.env['l10n_ua.budget.form_2d.wizard'].create({
            'estimate_id': self.estimate.id,
            'period': 'year',
        })
        result = wizard.action_print()
        self.assertEqual(result.get('type'), 'ir.actions.report')
        self.assertEqual(result.get('report_name'),
                          'l10n_ua_budget_reports.budget_form_2d_template')
        # data dict should be propagated
        self.assertEqual(result.get('data', {}).get('estimate_id'), self.estimate.id)


@tagged('post_install', '-at_install', 'l10n_ua_budget_reports')
class TestMemorialOrder16Offbalance(TransactionCase):
    """Тестування формування Меморіального ордера № 16-авт

    (Накопичувальна відомість позабалансового обліку) та його звірки з ОСВ.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1. Ізольована тестова компанія
        cls.company = cls.env['res.company'].create({
            'name': 'Тестова Установа МО-16',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.env = cls.env['res.company'].with_company(cls.company).env

        # 2. Позабалансові рахунки через Command.set
        cls.offbalance_acc = cls.env['account.account'].create({
            'name': 'Орендовані необоротні активи',
            'code': '011test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([cls.company.id])],
        })

        cls.contra_acc = cls.env['account.account'].create({
            'name': 'Балансуючий контра-рахунок',
            'code': '090test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([cls.company.id])],
        })

        cls.partner = cls.env['res.partner'].create({
            'name': 'Тестовий Орендодавець',
        })

        # 3. Дати розрахункового періоду
        cls.today = fields.Date.today()
        cls.period_start = cls.today.replace(day=1)
        cls.prior_date = cls.period_start - timedelta(days=5)

        # 4. Вхідний залишок (Opening move) у регістрі
        cls.open_move = cls.env['l10n_ua.offbalance.move'].create({
            'date': cls.prior_date,
            'company_id': cls.company.id,
            'ref': 'Вхідний договір № 50',
            'line_ids': [
                Command.create({
                    'account_id': cls.offbalance_acc.id,
                    'direction': 'debit',
                    'name': 'Початковий актив',
                    'partner_id': cls.partner.id,
                    'quantity': 1.0,
                    'amount': 50000.0,
                }),
            ],
        })
        cls.open_move.action_post()

        # 5. Обороти поточного періоду (Period move) у регістрі
        cls.period_move = cls.env['l10n_ua.offbalance.move'].create({
            'date': cls.today,
            'company_id': cls.company.id,
            'ref': 'Договір № 100',
            'line_ids': [
                Command.create({
                    'account_id': cls.offbalance_acc.id,
                    'direction': 'debit',
                    'name': 'Орендована будівля',
                    'partner_id': cls.partner.id,
                    'quantity': 2.0,
                    'amount': 150000.0,
                }),
            ],
        })
        cls.period_move.action_post()

        # 6. Історична проводка через account.move з парним контра-рахунком 090
        cls.journal = cls.env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16G',
            'type': 'general',
            'company_id': cls.company.id,
        })

        cls.hist_move = cls.env['account.move'].create({
            'journal_id': cls.journal.id,
            'company_id': cls.company.id,
            'date': cls.today,
            'line_ids': [
                Command.create({
                    'account_id': cls.offbalance_acc.id,
                    'name': 'Історичний актив',
                    'debit': 50000.0,
                    'credit': 0.0,
                    'quantity': 1.0,
                    'partner_id': cls.partner.id,
                }),
                Command.create({
                    'account_id': cls.contra_acc.id,
                    'name': 'Історичний балансуючий запис',
                    'debit': 0.0,
                    'credit': 50000.0,
                    'quantity': 1.0,
                    'partner_id': cls.partner.id,
                }),
            ],
        })
        cls.hist_move.action_post()

    def setUp(self):
        super().setUp()
        self.env.user.company_ids |= self.company
        self.env.user.company_id = self.company
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=[self.company.id]))
        self.env = self.env['res.company'].with_company(self.company).env

    def _create_wizard(self):
        """Допоміжний метод ініціалізації візарда МО-16."""
        return self.env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': self.company.id,
        })

    def test_01_memorial_order_16_report_data(self):
        """Перевірка збору рядків регістра, історичних проводок та розрахунку сальдо."""
        wizard = self._create_wizard()
        report_data = wizard.get_report_data()

        # Перевірка рядків із позабалансового регістра
        matching_rows = [r for r in report_data['rows_register'] if 'Орендована будівля' in r['description']]
        self.assertEqual(len(matching_rows), 1)
        self.assertEqual(matching_rows[0]['quantity'], 2.0)
        self.assertEqual(matching_rows[0]['debit'], 150000.0)
        self.assertEqual(matching_rows[0]['credit'], 0.0)
        self.assertEqual(matching_rows[0]['source'], 'register')
        self.assertEqual(matching_rows[0]['source_label'], 'Регістр')
        self.assertIn('Договір № 100', matching_rows[0]['move_name'])

        # Перевірка типової форми № 16-авт (таблиця з 6 колонок)
        rows_mo16 = report_data.get('rows_mo16', [])
        self.assertEqual(len(rows_mo16), 1)
        r0 = rows_mo16[0]
        self.assertEqual(r0['num'], 1)
        self.assertIn('Орендована будівля', r0['object_name'])
        self.assertIn('Тестовий Орендодавець', r0['object_name'])
        self.assertEqual(r0['debit_account'], '011test')
        self.assertEqual(r0['credit_account'], '—')
        self.assertEqual(r0['amount'], 150000.0)

        self.assertEqual(report_data['total_debit'], 150000.0)
        self.assertEqual(report_data['total_credit'], 0.0)
        self.assertEqual(report_data['total_turnover'], 150000.0)

        # Перевірка фільтрації технічного контра-рахунку 090test
        hist_rows = [r for r in report_data['rows_historical'] if 'Історичний актив' in r['description']]
        self.assertEqual(len(hist_rows), 1)
        self.assertEqual(hist_rows[0]['source'], 'historical')
        self.assertEqual(hist_rows[0]['source_label'], 'Історичні')
        self.assertEqual(hist_rows[0]['debit'], 50000.0)
        self.assertEqual(len(report_data['rows_historical']), 1, "Контра-рахунок 090 має бути відфільтрований")
        self.assertTrue(report_data.get('has_historical'))
        self.assertTrue(report_data.get('has_unmigrated_historical'))
        self.assertFalse(report_data.get('is_register_empty'))

        # Рядки rows мають містити виключно операції регістра (без змішування з історичними)
        self.assertEqual(len(report_data['rows']), 1)
        self.assertEqual(report_data['rows'][0]['source'], 'register')
        self.assertEqual(sum(r['debit'] for r in report_data['rows']), report_data['sum_debit'])

        # Перевірка підсумкових позицій за субрахунками
        positions = report_data.get('positions', [])
        self.assertEqual(len(positions), 1)
        pos0 = positions[0]
        self.assertEqual(pos0['account_code'], '011test')
        self.assertEqual(pos0['opening_balance'], 50000.0)
        self.assertEqual(pos0['opening_qty'], 1.0)
        self.assertEqual(pos0['sum_debit'], 150000.0)
        self.assertEqual(pos0['sum_qty_in'], 2.0)
        self.assertEqual(pos0['closing_balance'], 200000.0)
        self.assertEqual(pos0['closing_qty'], 3.0)

        # Загальні контрольні суми звіту
        self.assertEqual(report_data['opening_balance'], 50000.0)
        self.assertEqual(report_data['opening_qty'], 1.0)
        self.assertEqual(report_data['sum_register_debit'], 150000.0)
        self.assertEqual(report_data['sum_register_credit'], 0.0)
        self.assertEqual(report_data['sum_qty_in'], 2.0)
        self.assertEqual(report_data['sum_qty_out'], 0.0)
        self.assertEqual(report_data['closing_balance'], 200000.0)
        self.assertEqual(report_data['closing_qty'], 3.0)
        self.assertEqual(report_data['sum_historical_debit'], 50000.0)
        self.assertEqual(report_data['sum_historical_credit'], 0.0)
        self.assertEqual(report_data['sum_debit'], 150000.0)
        self.assertEqual(report_data['sum_credit'], 0.0)

    def test_02_reconciliation_with_osv_class_0(self):
        """Звірка контрольних сум меморіального ордера з ОСВ класу 0."""
        wizard = self._create_wizard()
        report_data = wizard.get_report_data()

        osv = self.env['l10n_ua.offbalance.osv'].create({
            'period_start': self.period_start,
            'period_end': self.today,
            'company_id': self.company.id,
        })
        osv.action_compute()

        osv_open_bal = sum(osv.line_ids.mapped(lambda l: l.opening_debit - l.opening_credit))
        osv_open_qty = sum(osv.line_ids.mapped('opening_qty'))
        osv_turn_d = sum(osv.line_ids.mapped('turnover_debit'))
        osv_turn_c = sum(osv.line_ids.mapped('turnover_credit'))
        osv_close_bal = sum(osv.line_ids.mapped(lambda l: l.closing_debit - l.closing_credit))
        osv_close_qty = sum(osv.line_ids.mapped('closing_qty'))

        self.assertEqual(report_data['opening_balance'], osv_open_bal, "МО-16 opening_balance must equal ОСВ класу 0")
        self.assertEqual(report_data['opening_qty'], osv_open_qty, "МО-16 opening_qty must equal ОСВ класу 0")
        self.assertEqual(report_data['sum_debit'], osv_turn_d, "МО-16 sum_debit must equal ОСВ класу 0 turnover_debit")
        self.assertEqual(report_data['sum_credit'], osv_turn_c, "МО-16 sum_credit must equal ОСВ класу 0 turnover_credit")
        self.assertEqual(report_data['closing_balance'], osv_close_bal, "МО-16 closing_balance must equal ОСВ класу 0")
        self.assertEqual(report_data['closing_qty'], osv_close_qty, "МО-16 closing_qty must equal ОСВ класу 0")

    def test_03_qweb_rendering_and_preview(self):
        """Перевірка коректності рендерингу друкованої форми та прев\'ю без docids."""
        self.company.external_report_layout_id = self.env.ref('web.external_layout_standard')

        wizard = self._create_wizard()
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')

        # 1. Стандартний рендеринг звіту
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html

        expected_tokens = [
            'Орендована будівля',
            'МЕМОРІАЛЬНИЙ ОРДЕР № 16-авт',
            '08.09.2017 № 755',
            'Накопичувальна відомість позабалансового обліку',
            'Усього до дебету субрахунків:',
            'Усього до кредиту рахунків:',
            'Сума оборотів за меморіальним ордером:',
            'Залишки на початок і кінець періоду (у розрізі позабалансових субрахунків)',
            'РАЗОМ за відомістю (збігається із загальним підсумком ОСВ класу 0)',
            'Додаток: Довідково — Історичні проводки',
            'РАЗОМ (довідково)',
        ]
        for token in expected_tokens:
            self.assertIn(token, html_str)

        self.assertNotIn('Ю.П. Романюк', html_str)

        # 2. Рендеринг у режимі прев\'ю без docids (наприклад, у base.document.layout)
        html_preview, _ = report._render_qweb_html(report.report_name, None, data=action_dict.get('data'))
        preview_str = html_preview.decode() if isinstance(html_preview, bytes) else html_preview

        preview_tokens = [
            'МЕМОРІАЛЬНИЙ ОРДЕР № 16-авт',
            '08.09.2017 № 755',
            'Орендована будівля',
            'Накопичувальна відомість позабалансового обліку',
        ]
        for token in preview_tokens:
            self.assertIn(token, preview_str)

        # 3. Плоский data при іншому env.company (розпаковується у top-level контекст QWeb)
        main_company = self.env.ref('base.main_company')
        html_flat, _ = report.with_company(main_company)._render_qweb_html(
            report.report_name,
            None,
            data={
                'mo_kind': 'mo_16',
                'company_id': self.company.id,
                'date_from': str(self.period_start),
                'date_to': str(self.today),
            },
        )
        flat_str = html_flat.decode() if isinstance(html_flat, bytes) else html_flat
        self.assertIn(self.company.name, flat_str)
        self.assertIn('Орендована будівля', flat_str)
        currency_symbol = self.company.currency_id.symbol or 'грн.'
        self.assertIn(f'Одиниця виміру:</strong> {currency_symbol}', flat_str)

        # 4. Порожній fallback (None, None) на компанії з виставленим external_report_layout_id
        html_empty, _ = report._render_qweb_html(report.report_name, None)
        empty_str = html_empty.decode() if isinstance(html_empty, bytes) else html_empty
        self.assertIn('МО-2 Рух коштів загального фонду', empty_str)
        self.assertIn(str(fields.Date.today().replace(day=1)), empty_str)

    def test_04_unmigrated_historical_warning(self):
        """Якщо регістр позабалансу порожній, але є проводки account.move.line, має виводитися попередження."""
        unmigrated_company = self.env['res.company'].create({
            'name': 'Установа Без Міграції',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= unmigrated_company
        unmigrated_env = self.env(context=dict(self.env.context, allowed_company_ids=[unmigrated_company.id]))
        unmigrated_env = unmigrated_env['res.company'].with_company(unmigrated_company).env

        acc = unmigrated_env['account.account'].create({
            'name': 'Орендовані активи старі',
            'code': '012test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([unmigrated_company.id])],
        })
        contra = unmigrated_env['account.account'].create({
            'name': 'Балансуючий контра-рахунок старий',
            'code': '091test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([unmigrated_company.id])],
        })
        journal = unmigrated_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16U',
            'type': 'general',
            'company_id': unmigrated_company.id,
        })
        move = unmigrated_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': unmigrated_company.id,
            'date': self.today,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Немігрований актив',
                    'debit': 75000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра запис',
                    'debit': 0.0,
                    'credit': 75000.0,
                }),
            ],
        })
        move.action_post()

        wizard = unmigrated_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': unmigrated_company.id,
        })
        report_data = wizard.get_report_data()
        self.assertTrue(report_data.get('has_unmigrated_historical'))
        self.assertEqual(report_data['sum_debit'], 0.0)

        unmigrated_company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('У звітному періоді виявлено операції подвійного запису на позабалансових субрахунках', html_str)

    def test_05_unmigrated_prior_balance_warning(self):
        """Якщо в минулому періоді є несторновані проводки account.move.line, а регістр на початок порожній."""
        comp = self.env['res.company'].create({
            'name': 'Установа Із Завислим Сальдо',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp
        c_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp.id]))
        c_env = c_env['res.company'].with_company(comp).env

        acc = c_env['account.account'].create({
            'name': 'Орендовані активи 2025',
            'code': '013test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        contra = c_env['account.account'].create({
            'name': 'Балансуючий контра-рахунок 2025 (не 09)',
            'code': '022test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        journal = c_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16P',
            'type': 'general',
            'company_id': comp.id,
        })
        # Проводка минулого періоду (до date_from)
        move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': comp.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Минулий актив',
                    'debit': 120000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра запис',
                    'debit': 0.0,
                    'credit': 120000.0,
                }),
            ],
        })
        move.action_post()

        wizard = c_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp.id,
        })
        report_data = wizard.get_report_data()
        self.assertTrue(report_data.get('has_unmigrated_prior_balance'))
        self.assertFalse(report_data.get('has_unreversed_prior_balance'))
        self.assertEqual(report_data.get('hist_prior_balance'), 120000.0)

        comp.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Виявлено неперенесені залишки минулих періодів', html_str)

    def test_06_unreversed_prior_balance_warning(self):
        """Якщо в регістр введено залишок, але стару проводку минулого періоду не сторнували (ризик задвоєння)."""
        comp = self.env['res.company'].create({
            'name': 'Установа Задвоєння',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp
        c_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp.id]))
        c_env = c_env['res.company'].with_company(comp).env

        acc = c_env['account.account'].create({
            'name': 'Орендовані активи подвійні',
            'code': '014test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        contra = c_env['account.account'].create({
            'name': 'Балансуючий контра подвійний (не 09)',
            'code': '023test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        journal = c_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16D',
            'type': 'general',
            'company_id': comp.id,
        })
        # 1. Стара проводка минулого періоду (не сторнована!)
        move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': comp.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Старий актив',
                    'debit': 90000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра запис',
                    'debit': 0.0,
                    'credit': 90000.0,
                }),
            ],
        })
        move.action_post()

        # 2. Новий регістр: вхідний залишок введено
        open_move = c_env['l10n_ua.offbalance.move'].create({
            'date': self.prior_date,
            'company_id': comp.id,
            'ref': 'Введення залишків',
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'direction': 'debit',
                    'name': 'Новий залишок',
                    'quantity': 1.0,
                    'amount': 90000.0,
                }),
            ],
        })
        open_move.action_post()

        wizard = c_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp.id,
        })
        report_data = wizard.get_report_data()
        self.assertFalse(report_data.get('has_unmigrated_prior_balance'))
        self.assertTrue(report_data.get('has_unreversed_prior_balance'))
        self.assertEqual(report_data.get('hist_prior_balance'), 90000.0)
        self.assertEqual(report_data.get('opening_balance'), 90000.0)

        comp.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('ризик подвійного обліку', html_str)

    def test_07_transitional_reversal_no_false_warning(self):
        """Штатне сторно через account.move.reversal у поточному періоді не дає помилкового алерта."""
        comp = self.env['res.company'].create({
            'name': 'Установа Штатне Сторно',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp
        c_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp.id]))
        c_env = c_env['res.company'].with_company(comp).env

        acc = c_env['account.account'].create({
            'name': 'Орендовані активи сторно',
            'code': '015test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        contra = c_env['account.account'].create({
            'name': 'Контра-рахунок сторно',
            'code': '095test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        journal = c_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16R',
            'type': 'general',
            'company_id': comp.id,
        })
        # 1. До period_start: стара проводка Дт 01 / Кт 09 + запис у регістр
        old_move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': comp.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Актив до сторнування',
                    'debit': 80000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра до сторнування',
                    'debit': 0.0,
                    'credit': 80000.0,
                }),
            ],
        })
        old_move.action_post()

        open_move = c_env['l10n_ua.offbalance.move'].create({
            'date': self.prior_date,
            'company_id': comp.id,
            'ref': 'Введення залишку',
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'direction': 'debit',
                    'name': 'Залишок у регістрі',
                    'quantity': 1.0,
                    'amount': 80000.0,
                }),
            ],
        })
        open_move.action_post()

        # 2. У поточному періоді: штатне сторно через account.move.reversal
        rev_wizard = c_env['account.move.reversal'].with_context(
            active_model='account.move',
            active_ids=old_move.ids,
        ).create({
            'date': self.today,
            'journal_id': journal.id,
        })
        rev_wizard.refund_moves()
        self.assertTrue(old_move.reversal_move_ids.filtered(lambda m: m.reversed_entry_id == old_move))

        wizard = c_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp.id,
        })
        report_data = wizard.get_report_data()
        self.assertFalse(report_data.get('has_unmigrated_historical'))
        self.assertTrue(report_data.get('has_historical'))
        self.assertEqual(len(report_data['rows_historical']), 1)

        comp.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertNotIn('У звітному періоді виявлено операції подвійного запису на позабалансових субрахунках', html_str)
        self.assertNotIn('паралельний облік в', html_str)

    def test_08_unmigrated_both_prior_and_current_alerts(self):
        """Порожній регістр + несторнований залишок до period_start + поточна проводка показують обидва алерти."""
        comp = self.env['res.company'].create({
            'name': 'Установа Обидва Алерти',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp
        c_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp.id]))
        c_env = c_env['res.company'].with_company(comp).env

        acc = c_env['account.account'].create({
            'name': 'Орендовані активи змішані',
            'code': '016test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        contra = c_env['account.account'].create({
            'name': 'Контра змішана',
            'code': '096test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp.id])],
        })
        journal = c_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16B',
            'type': 'general',
            'company_id': comp.id,
        })
        prior_move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': comp.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Минулий залишок',
                    'debit': 100000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра минулий',
                    'debit': 0.0,
                    'credit': 100000.0,
                }),
            ],
        })
        prior_move.action_post()

        curr_move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': comp.id,
            'date': self.today,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Поточна операція',
                    'debit': 50000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра поточна',
                    'debit': 0.0,
                    'credit': 50000.0,
                }),
            ],
        })
        curr_move.action_post()

        wizard = c_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp.id,
        })
        report_data = wizard.get_report_data()
        self.assertTrue(report_data.get('has_unmigrated_prior_balance'))
        self.assertEqual(report_data.get('hist_prior_balance'), 100000.0)
        self.assertTrue(report_data.get('has_unmigrated_historical'))
        self.assertTrue(report_data.get('is_register_empty'))

        comp.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Виявлено неперенесені залишки минулих періодів', html_str)
        self.assertIn('У звітному періоді виявлено операції подвійного запису на позабалансових субрахунках', html_str)

    def test_09_psbo_09_and_budget_0009_prior_detection(self):
        """Рахунок П(С)БО 09 та бюджетна пара 0001/0009 коректно виявляються без фільтра 09%."""
        # 1. Компанія П(С)БО з реальним позабалансовим рахунком 09 (Дт 09 / Кт 00 до періоду + самостійний 09 у періоді)
        comp_psbo = self.env['res.company'].create({
            'name': 'Установа ПСБО 09',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp_psbo
        p_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp_psbo.id]))
        p_env = p_env['res.company'].with_company(comp_psbo).env

        acc_09 = p_env['account.account'].create({
            'name': 'Амортизаційні відрахування',
            'code': '09',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp_psbo.id])],
        })
        acc_00 = p_env['account.account'].create({
            'name': 'Технічний контр-рахунок',
            'code': '00',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp_psbo.id])],
        })
        acc_091 = p_env['account.account'].create({
            'name': 'Амортизаційні відрахування (субрахунок)',
            'code': '091test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp_psbo.id])],
        })
        journal_p = p_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'PS09',
            'type': 'general',
            'company_id': comp_psbo.id,
        })
        prior_09 = p_env['account.move'].create({
            'journal_id': journal_p.id,
            'company_id': comp_psbo.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc_09.id,
                    'name': 'Нарахована амортизація',
                    'debit': 40000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': acc_00.id,
                    'name': 'Контр-рахунок 00',
                    'debit': 0.0,
                    'credit': 40000.0,
                }),
            ],
        })
        prior_09.action_post()

        curr_09 = p_env['account.move'].create({
            'journal_id': journal_p.id,
            'company_id': comp_psbo.id,
            'date': self.today,
            'line_ids': [
                Command.create({
                    'account_id': acc_09.id,
                    'name': 'Самостійний рух 09',
                    'debit': 10000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': acc_091.id,
                    'name': 'Субрахунок 091',
                    'debit': 0.0,
                    'credit': 10000.0,
                }),
            ],
        })
        curr_09.action_post()

        wiz_psbo = p_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp_psbo.id,
        })
        data_psbo = wiz_psbo.get_report_data()
        self.assertEqual(data_psbo.get('hist_prior_balance'), 40000.0)
        self.assertTrue(data_psbo.get('has_unmigrated_prior_balance'))
        self.assertTrue(data_psbo.get('has_historical'))
        self.assertEqual(len(data_psbo['rows_historical']), 2)
        self.assertEqual({r['account_code'] for r in data_psbo['rows_historical']}, {'09', '091test'})

        # 2. Бюджетна компанія з парою 0001 / 0009
        comp_budget = self.env['res.company'].create({
            'name': 'Установа Бюджет 0001/0009',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= comp_budget
        b_env = self.env(context=dict(self.env.context, allowed_company_ids=[comp_budget.id]))
        b_env = b_env['res.company'].with_company(comp_budget).env

        acc_0001 = b_env['account.account'].create({
            'name': 'Орендовані основні засоби',
            'code': '0001',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp_budget.id])],
        })
        acc_0009 = b_env['account.account'].create({
            'name': 'Призначення та зобов’язання за фондом',
            'code': '0009',
            'account_type': 'off_balance',
            'company_ids': [Command.set([comp_budget.id])],
        })
        journal_b = b_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'BG09',
            'type': 'general',
            'company_id': comp_budget.id,
        })
        prior_budget = b_env['account.move'].create({
            'journal_id': journal_b.id,
            'company_id': comp_budget.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc_0001.id,
                    'name': 'Бюджетний об’єкт',
                    'debit': 60000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': acc_0009.id,
                    'name': 'Контр-рахунок 0009',
                    'debit': 0.0,
                    'credit': 60000.0,
                }),
            ],
        })
        prior_budget.action_post()

        wiz_budget = b_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': comp_budget.id,
        })
        data_budget = wiz_budget.get_report_data()
        self.assertEqual(data_budget.get('hist_prior_balance'), 60000.0)
        self.assertTrue(data_budget.get('has_unmigrated_prior_balance'))
