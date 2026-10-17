"""Друк звітів-майстрів має давати непорожній документ (#299).

Клієнт (web/static/src/webclient/actions/reports/utils.js, getReportUrl)
при непорожньому ``action['data']`` будує URL ``?options=…`` без docids,
і шаблон з ``t-foreach="docs"`` рендериться порожнім. Тест відтворює це
правило: бере ids так само, як їх бере клієнт, і рендерить звіт.
"""

from odoo.tests import tagged
from .common import AccountingTestCase


@tagged('post_install', '-at_install')
class TestWizardPrint(AccountingTestCase):

    @staticmethod
    def _report_action(action):
        if action.get('type') != 'ir.actions.report':
            # Гілка конфігуратора лого: справжня дія лежить у контексті.
            action = action['context']['report_action']
        return action

    def _client_docids(self, action):
        """docids, які потраплять у URL звіту за правилом getReportUrl."""
        action = self._report_action(action)
        if action.get('data'):
            return None
        return action['context'].get('active_ids')

    def _render_as_client(self, action):
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            self._report_action(action)['report_name'],
            self._client_docids(action),
        )
        return html.decode()

    def _assert_prints(self, wizard, marker):
        for action in (
            wizard.with_context(discard_logo_check=True).action_print(),
            # Без discard_logo_check на свіжій базі — шлях конфігуратора лого.
            wizard.with_context(discard_logo_check=False).action_print(),
        ):
            self.assertEqual(self._client_docids(action), wizard.ids)
            self.assertIn(marker, self._render_as_client(action))

    def test_reconciliation_act_not_empty(self):
        wizard = self.env['l10n_ua.reconciliation.act.wizard'].create({
            'partner_id': self.partner.id,
            'date_from': '2020-01-01',
            'date_to': '2030-12-31',
        })
        self._assert_prints(wizard, 'АКТ ЗВІРКИ ВЗАЄМОРОЗРАХУНКІВ')

    def test_cash_book_not_empty(self):
        wizard = self.env['l10n_ua.cash.book.wizard'].create({
            'journal_id': self.cash_journal.id,
            'date_from': '2020-01-01',
            'date_to': '2030-12-31',
        })
        self._assert_prints(wizard, 'КО-4')
