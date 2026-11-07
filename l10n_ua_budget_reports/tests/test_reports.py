"""Tests for budget reports — render to HTML without errors."""
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
                (0, 0, {
                    'kekv_id': cls.kekv_2111.id, 'fund_type': 'general',
                    'm01': 1000, 'm06': 2000, 'm12': 3000,
                }),
                (0, 0, {
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

    def test_memorial_order_16_offbalance(self):
        """MO-16 should collect lines from l10n_ua.offbalance.move.line with quantity and AML with source markers."""
        from odoo import fields
        company = self.env['res.company'].create({
            'name': 'Тестова Установа МО-16',
            'country_id': self.env.ref('base.ua').id,
        })
        self.env.user.company_ids |= company

        offbalance_acc = self.env['account.account'].create({
            'name': 'Орендовані необоротні активи',
            'code': '011test',
            'account_type': 'off_balance',
            'company_ids': [(6, 0, [company.id])],
        })

        partner = self.env['res.partner'].create({'name': 'Тестовий Орендодавець'})
        today = fields.Date.today()
        move = self.env['l10n_ua.offbalance.move'].create({
            'date': today,
            'company_id': company.id,
            'ref': 'Договір № 100',
            'line_ids': [(0, 0, {
                'account_id': offbalance_acc.id,
                'direction': 'debit',
                'name': 'Орендована будівля',
                'partner_id': partner.id,
                'quantity': 2.0,
                'amount': 150000.0,
            })],
        })
        move.action_post()

        # Add historical entry (account.move.line)
        journal = self.env['account.journal'].create({
            'name': 'Операції вручну',
            'code': 'MO16G',
            'type': 'general',
            'company_id': company.id,
        })
        hist_move = self.env['account.move'].create({
            'journal_id': journal.id,
            'company_id': company.id,
            'date': today,
            'line_ids': [
                (0, 0, {
                    'account_id': offbalance_acc.id,
                    'name': 'Історичний актив',
                    'debit': 50000.0,
                    'credit': 0.0,
                    'quantity': 1.0,
                    'partner_id': partner.id,
                }),
                (0, 0, {
                    'account_id': offbalance_acc.id,
                    'name': 'Історичний балансуючий запис',
                    'debit': 0.0,
                    'credit': 50000.0,
                    'quantity': 1.0,
                    'partner_id': partner.id,
                }),
            ],
        })
        hist_move.action_post()

        wizard = self.env['l10n_ua.budget.memorial_order.wizard'].create({
            'mo_kind': 'mo_16',
            'date_from': today.replace(day=1),
            'date_to': today,
            'company_id': company.id,
        })
        report_data = wizard.get_report_data()
        matching_rows = [r for r in report_data['rows'] if 'Орендована будівля' in r['description']]
        self.assertEqual(len(matching_rows), 1)
        self.assertEqual(matching_rows[0]['quantity'], 2.0)
        self.assertEqual(matching_rows[0]['debit'], 150000.0)
        self.assertEqual(matching_rows[0]['credit'], 0.0)
        self.assertEqual(matching_rows[0]['source'], 'register')
        self.assertEqual(matching_rows[0]['source_label'], 'Регістр')
        self.assertIn('Договір № 100', matching_rows[0]['move_name'])

        hist_rows = [r for r in report_data['rows'] if 'Історичний актив' in r['description']]
        self.assertEqual(len(hist_rows), 1)
        self.assertEqual(hist_rows[0]['source'], 'historical')
        self.assertEqual(hist_rows[0]['source_label'], 'Історичні')
        self.assertEqual(hist_rows[0]['debit'], 50000.0)

        self.assertTrue(report_data.get('has_historical'))
        self.assertEqual(report_data['sum_register_debit'], 150000.0)
        self.assertEqual(report_data['sum_register_credit'], 0.0)
        self.assertEqual(report_data['sum_historical_debit'], 50000.0)
        self.assertEqual(report_data['sum_historical_credit'], 50000.0)
        self.assertEqual(report_data['sum_debit'], 150000.0)
        self.assertEqual(report_data['sum_credit'], 0.0)

        # Check trial balance (OSV Class 0) reconciliation
        osv = self.env['l10n_ua.offbalance.osv'].create({
            'period_start': today.replace(day=1),
            'period_end': today,
            'company_id': company.id,
        })
        osv.action_compute()
        self.assertEqual(
            sum(osv.line_ids.mapped('turnover_debit')),
            report_data['sum_debit'],
            "МО-16 sum_debit must equal ОСВ класу 0 turnover_debit"
        )
        self.assertEqual(
            sum(osv.line_ids.mapped('turnover_credit')),
            report_data['sum_credit'],
            "МО-16 sum_credit must equal ОСВ класу 0 turnover_credit"
        )

        # Check rendering of the QWeb template
        company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        action_dict = wizard.action_print()
        report = self.env.ref('l10n_ua_budget_reports.action_report_memorial_order')
        html, _ = report._render_qweb_html(report.report_name, [wizard.id], data=action_dict.get('data'))
        html_str = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Орендована будівля', html_str)
        self.assertIn('150 000.00', html_str)
        self.assertIn('Регістр позабалансового обліку', html_str)
        self.assertIn('Довідково: Історичні проводки', html_str)
        self.assertIn('РАЗОМ (збігається з ОСВ класу 0)', html_str)
        self.assertIn('РАЗОМ (довідково)', html_str)

        # Check rendering when called without docids (as in base.document.layout preview /report/html/)
        html_preview, _ = report._render_qweb_html(report.report_name, None, data=action_dict.get('data'))
        preview_str = html_preview.decode() if isinstance(html_preview, bytes) else html_preview
        self.assertIn('Орендована будівля', preview_str)
        self.assertIn('150 000.00', preview_str)
        self.assertIn('Регістр позабалансового обліку', preview_str)
