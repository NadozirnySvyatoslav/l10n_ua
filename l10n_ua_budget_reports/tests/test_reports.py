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
        matching_rows = [r for r in report_data['rows_mo16'] if 'Орендована будівля' in r['description']]
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

        # Перевірка прапорця несторнованих залишків у старій схемі account.move.line
        self.assertTrue(report_data.get('has_unreversed_legacy_moves'))

        # Рядки rows_mo16 мають містити виключно операції регістра (без змішування з історичними)
        self.assertEqual(len(report_data['rows_mo16']), 1)
        self.assertEqual(report_data['rows_mo16'][0]['source'], 'register')
        self.assertEqual(sum(r['debit'] for r in report_data['rows_mo16']), report_data['sum_debit'])

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
            'Увага (несторновані старі проводки)',
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

    def test_04_legacy_unreversed_balance_warning(self):
        """Перевірка попередження про старі несторновані проводки та його зникнення після сторнування."""
        clean_company = self.env['res.company'].create({
            'name': 'Чиста Установа',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= clean_company
        c_env = self.env(context=dict(self.env.context, allowed_company_ids=[clean_company.id]))
        c_env = c_env['res.company'].with_company(clean_company).env

        acc = c_env['account.account'].create({
            'name': 'Орендовані активи',
            'code': '013test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([clean_company.id])],
        })
        contra = c_env['account.account'].create({
            'name': 'Контра-рахунок',
            'code': '093test',
            'account_type': 'off_balance',
            'company_ids': [Command.set([clean_company.id])],
        })

        wiz = c_env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': self.period_start,
            'date_to': self.today,
            'company_id': clean_company.id,
        })

        # 1. Поки немає проводок в account.move.line — прапорець False
        self.assertFalse(wiz.get_report_data()['has_unreversed_legacy_moves'])

        # 2. Створюємо стару проводку за подвійним записом Дт 013 / Кт 093
        journal = c_env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16C',
            'type': 'general',
            'company_id': clean_company.id,
        })
        move = c_env['account.move'].create({
            'journal_id': journal.id,
            'company_id': clean_company.id,
            'date': self.prior_date,
            'line_ids': [
                Command.create({
                    'account_id': acc.id,
                    'name': 'Старий актив',
                    'debit': 80000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': contra.id,
                    'name': 'Контра запис',
                    'debit': 0.0,
                    'credit': 80000.0,
                }),
            ],
        })
        move.action_post()

        # Тепер на рахунках 013 та 093 є ненульове сальдо — прапорець True
        self.assertTrue(wiz.get_report_data()['has_unreversed_legacy_moves'])

        clean_company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wiz.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wiz.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Увага (несторновані старі проводки)', html_str)

        # 3. Виконуємо стандартне сторнування (реверс) старої проводки
        reversed_moves = move._reverse_moves(default_values_list=[{'date': self.today}], cancel=False)
        reversed_moves.action_post()

        # Сальдо рахунків 013 та 093 стало 0.00 — попередження зникає (False)
        self.assertFalse(wiz.get_report_data()['has_unreversed_legacy_moves'])
