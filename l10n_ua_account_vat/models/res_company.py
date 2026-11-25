"""Extension of res.company with Ukrainian VAT payer settings."""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_is_vat_payer = fields.Boolean(
        string='Платник ПДВ',
        default=False,
    )
    l10n_ua_vat_registration_date = fields.Date(
        string='Дата реєстрації платником ПДВ',
    )
    l10n_ua_vat_ipn = fields.Char(
        string='ІПН платника ПДВ',
        size=12,
        help='Індивідуальний податковий номер платника ПДВ',
    )
    l10n_ua_vat_signer_name = fields.Char(
        string='Особа, що складає ПН',
        help='Ініціали та прізвище (власне ім\'я ПРІЗВИЩЕ) особи, яка складає й підписує податкові '
             'накладні (HBOS).')
    l10n_ua_vat_signer_rnokpp = fields.Char(
        string='РНОКПП особи, що складає ПН', size=10)
    l10n_ua_erpn_deadline_mode = fields.Selection(
        selection=[
            ('wartime', 'Воєнний час (5-те/18-те наст. місяця)'),
            ('peacetime', 'Мирний час (останній день/15-те наст. місяця)'),
        ],
        string='Режим строків ЄРПН',
        default='wartime',
        help='Воєнний час: 1-15 числа → 5-те наст. місяця, 16-кінець → 18-те наст. місяця.\n'
             'Мирний час: 1-15 числа → останній день місяця, 16-кінець → 15-те наст. місяця.',
    )
