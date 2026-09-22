from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..tools.validators import validate_iban_ua


class ResPartnerBank(models.Model):
    """Український банківський рахунок: МФО та банк — з самого IBAN.

    В українському IBAN (UAkk MFOOOO ...) МФО стоїть на позиціях 5-10,
    одразу після контрольного розряду. Тобто рахунок сам себе описує:
    користувачу достатньо ввести IBAN, а назва банку й МФО підставляються
    з довідника ``l10n_ua.bank``.
    """
    _inherit = 'res.partner.bank'

    l10n_ua_mfo = fields.Char(
        string='MFO',
        compute='_compute_l10n_ua_mfo',
        store=True,
        index='btree_not_null',
        help='МФО банку, прочитане з IBAN (позиції 5-10).',
    )
    l10n_ua_bank_id = fields.Many2one(
        'l10n_ua.bank',
        string='Ukrainian Bank',
        compute='_compute_l10n_ua_bank_id',
        store=True,
        readonly=False,
        index='btree_not_null',
        help='Банк із довідника МФО. Підставляється з IBAN, але його '
             'можна перевизначити вручну.',
    )
    l10n_ua_bank_name = fields.Char(
        string='Bank Name (UA)',
        compute='_compute_l10n_ua_bank_name',
        help='Назва банку для друкованих форм: із довідника МФО, а якщо '
             'банку там немає — те, що введено в рахунку.',
    )

    @api.depends('sanitized_account_number')
    def _compute_l10n_ua_mfo(self):
        for account in self:
            iban = (account.sanitized_account_number or '').upper()
            mfo = iban[4:10] if iban[:2] == 'UA' else ''
            account.l10n_ua_mfo = mfo if mfo.isdigit() else False

    @api.depends('l10n_ua_mfo')
    def _compute_l10n_ua_bank_id(self):
        Bank = self.env['l10n_ua.bank']
        for account in self:
            # Банк, проставлений вручну, лишається: довідник неповний, і
            # для МФО, якого в ньому ще немає, вибір користувача — єдине
            # джерело назви банку.
            account.l10n_ua_bank_id = (
                Bank._find_by_mfo(account.l10n_ua_mfo)
                or account.l10n_ua_bank_id)

    @api.depends('l10n_ua_bank_id', 'bank_name')
    def _compute_l10n_ua_bank_name(self):
        for account in self:
            account.l10n_ua_bank_name = (
                account.l10n_ua_bank_id.name or account.bank_name or '')

    @api.constrains('account_number')
    def _check_iban_ua(self):
        """Контрольний розряд українського IBAN.

        Перевіряємо ``sanitized_account_number``: Odoo 20 зберігає IBAN
        відформатованим (``UA21 3223 …``), а валідатор чекає суцільні
        29 символів.
        """
        for account in self:
            iban = (account.sanitized_account_number or '').upper()
            if not iban.startswith('UA'):
                continue
            is_valid, error = validate_iban_ua(iban)
            if not is_valid:
                raise ValidationError(
                    _('Invalid Ukrainian IBAN: %s') % error)
