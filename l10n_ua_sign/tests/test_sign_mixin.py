"""Тести домішки клієнтського КЕП-підпису (l10n_ua.sign.mixin).

Домішку перевіряємо напряму (порожній browse-запис — Odoo 20 не дає
робити .new() на абстрактній моделі, а жодного з методів БД не торкається):
- action_kep_sign повертає правильний client action із model/res_id;
- дефолтні kep_prepare_signing/kep_submit_signed кидають UserError
  (щоб споживач був змушений їх реалізувати).

Повноцінно домішка покривається тестами реальних споживачів (ЄРПН, декларації).
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSignMixin(TransactionCase):

    def _rec(self):
        return self.env['l10n_ua.sign.mixin'].browse(1)

    def test_action_returns_client_action(self):
        action = self._rec().action_kep_sign()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(action['params']['model'], 'l10n_ua.sign.mixin')
        self.assertIn('res_id', action['params'])
        self.assertNotIn('mode', action['params'])

    def test_action_passes_mode(self):
        action = self._rec().action_kep_sign(mode='submit')
        self.assertEqual(action['params']['mode'], 'submit')

    def test_prepare_default_raises(self):
        with self.assertRaises(UserError):
            self._rec().kep_prepare_signing()

    def test_submit_default_raises(self):
        with self.assertRaises(UserError):
            self._rec().kep_submit_signed({})
