"""Фінзвіти l10n_ua_accounting з XML ДПС і поданням."""
from odoo import _, models
from odoo.exceptions import UserError


class L10nUaBalanceReport(models.Model):
    _name = 'l10n_ua.balance.report'
    _inherit = ['l10n_ua.balance.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0900108'

    def _fin_dps_period(self):
        # Баланс — на дату: тип періоду за кінцем кварталу, початку немає.
        period_type, month, _text = super()._fin_dps_period()
        return period_type, month, self._fin_dps_balance_date_text()

    def _fin_dps_header(self, period_text):
        # H01 — за НП(С)БО, H02 — за МСФЗ (вибір у схемі).
        return {'H01': '1'}


class L10nUaPnlReport(models.Model):
    _name = 'l10n_ua.pnl.report'
    _inherit = ['l10n_ua.pnl.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0900207'


class L10nUaCashflowReport(models.Model):
    _name = 'l10n_ua.cashflow.report'
    _inherit = ['l10n_ua.cashflow.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0901602' if self.method == 'indirect' else 'J0900904'


class L10nUaEquityReport(models.Model):
    _name = 'l10n_ua.equity.report'
    _inherit = ['l10n_ua.equity.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0901005'


class L10nUaSmallReport(models.Model):
    _name = 'l10n_ua.small.report'
    _inherit = ['l10n_ua.small.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0901205' if self.kind == 'micro' else 'J0901107'

    def _fin_dps_header(self, period_text):
        # «Баланс на 31 грудня 2026 р.» і «Звіт про фінансові результати за рік 2026 р.».
        return {
            'HPERIOD': self._fin_dps_balance_date_text(),
            'HPERIOD1': period_text,
            'HZY1': str(self.date_to.year),
        }


class L10nUaNotesReport(models.Model):
    _name = 'l10n_ua.notes.report'
    _inherit = ['l10n_ua.notes.report', 'l10n_ua.fin.report.dps.mixin']

    # Перерахунок і повернення в чернетку скидають XML; поданий звіт — ні.
    def action_compute(self):
        self._fin_dps_reset()
        return super().action_compute()

    def action_draft(self):
        self._fin_dps_reset()
        return super().action_draft()

    def _fin_dps_form(self):
        return 'J0901301'

    def _fin_dps_period(self):
        # Примітки (ф. № 5) — лише річна звітність (НП(С)БО 1, п. 2 розд. I).
        period_type, month, text = super()._fin_dps_period()
        if month != 12:
            raise UserError(_('Примітки до фінансової звітності (ф. № 5) подаються лише за рік: '
                              'період — з 1 січня до 31 грудня.'))
        return period_type, month, text
