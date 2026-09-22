import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

MFO_RE = re.compile(r'^\d{6}$')


class L10nUaBank(models.Model):
    """Довідник банків України за кодом МФО.

    Odoo 20 прибрало `res.bank` разом із `res.partner.bank.bank_id`:
    реквізити банку стали денормалізованими полями рахунку
    (`bank_name`, `bank_bic`). Для України цього мало — МФО є в кожній
    платіжці й у кожній друкованій формі («в банку X, МФО Y»), і його
    треба вміти розгорнути в назву банку, а не переписувати руками на
    кожному рахунку.

    МФО живе в самому IBAN (UAkk **MFOOOO** ...), тому рахунок знаходить
    свій банк сам — див. `res.partner.bank._compute_l10n_ua_bank_id`.
    """
    _name = 'l10n_ua.bank'
    _description = 'Ukrainian Bank (MFO Directory)'
    _order = 'name'
    _rec_names_search = ['name', 'mfo']

    name = fields.Char(string='Name', required=True, translate=True)
    mfo = fields.Char(
        string='MFO',
        size=6,
        required=True,
        index=True,
        help='Код банку в системі електронних платежів НБУ — 6 цифр.',
    )
    edrpou = fields.Char(
        string='EDRPOU',
        size=8,
        help='Код ЄДРПОУ банку — деякі платіжні формати вимагають його '
             'окремо від МФО.',
    )
    bic = fields.Char(
        string='SWIFT/BIC',
        help='Міжнародний код банку для валютних переказів.',
    )
    active = fields.Boolean(default=True)

    _unique_mfo = models.Constraint(
        'UNIQUE(mfo)',
        'МФО має бути унікальним — два банки з одним МФО неможливі!',
    )

    @api.constrains('mfo')
    def _check_mfo(self):
        for bank in self:
            if bank.mfo and not MFO_RE.match(bank.mfo):
                raise ValidationError(
                    _('МФО «%s» некоректне: очікується рівно 6 цифр.')
                    % bank.mfo)

    @api.depends('name', 'mfo')
    def _compute_display_name(self):
        for bank in self:
            bank.display_name = f'{bank.name} ({bank.mfo})' if bank.mfo \
                else bank.name

    @api.model
    def _find_by_mfo(self, mfo):
        """Банк за МФО або порожній набір. Архівні теж враховуються:
        банк, що змінив назву чи пішов із ринку, лишається в старих
        документах."""
        if not mfo or not MFO_RE.match(mfo):
            return self.browse()
        return self.with_context(active_test=False).search(
            [('mfo', '=', mfo)], limit=1)
