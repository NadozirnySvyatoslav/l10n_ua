from datetime import date

from odoo.tests import tagged

from .common import AgroLandTestCase


@tagged('post_install', '-at_install')
class TestLandRentPdfoRate(AgroLandTestCase):
    """#545: ПДФО з оренди землі/паїв лишається 18 % і після Закону № 5025-IX."""

    def test_default_rates(self):
        company = self.env['res.company'].create({'name': 'Агро (тест #545)'})
        self.assertEqual(company.l10n_ua_agro_pdfo_rate, 18.0)
        self.assertEqual(company.l10n_ua_agro_military_rate, 5.0)

    def test_help_mentions_land_exception(self):
        help_text = self.env['res.company']._fields['l10n_ua_agro_pdfo_rate'].help
        self.assertIn('5025-IX', help_text)
        self.assertIn('до землі НЕ застосовується', help_text)

    def test_rate_does_not_depend_on_date(self):
        self._lease(self.lessor, self.plot1, date_start=date(2026, 1, 1))   # 9 600 / рік
        accrual = self.env['l10n_ua.agro.rent.accrual'].create({
            'date': date(2026, 10, 15),
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 12, 31)})
        # до і після набрання чинності Законом № 5025-IX (23.10.2026)
        for accrual_date in (date(2026, 10, 15), date(2026, 10, 31)):
            accrual.date = accrual_date
            accrual.action_compute()
            line = accrual.line_ids
            self.assertEqual(line.amount, 9600.0)
            self.assertEqual(line.pdfo_amount, 1728.0)
            self.assertEqual(line.military_amount, 480.0)
            self.assertEqual(line.net_amount, 7392.0)

    def test_rate_change_keeps_posted_accrual(self):
        self._lease(self.lessor, self.plot1)
        posted = self._accrual()
        posted.action_post()
        self.company.l10n_ua_agro_pdfo_rate = 5.0
        self.assertEqual(posted.line_ids.pdfo_rate, 18.0)
        self.assertEqual(posted.line_ids.pdfo_amount, 1728.0)
        new = self._accrual(date(2097, 1, 1), date(2097, 12, 31))
        self.assertEqual(new.line_ids.pdfo_rate, 5.0)
        self.assertEqual(new.line_ids.pdfo_amount, 480.0)

    def test_settings_warn_but_do_not_block(self):
        settings = self.env['res.config.settings'].create({})
        self.assertFalse(settings._onchange_l10n_ua_agro_pdfo_rate())
        settings.l10n_ua_agro_pdfo_rate = 5.0
        result = settings._onchange_l10n_ua_agro_pdfo_rate()
        self.assertIn('warning', result)
        settings.execute()
        self.assertEqual(self.company.l10n_ua_agro_pdfo_rate, 5.0)
