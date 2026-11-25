"""Реквізити, без яких XML податкової накладної (J1201016) не формується."""


def set_pn_requisites(env, company):
    Office = env['l10n_ua.tax.office'].sudo()
    office = Office.search([('code', '=', '2650')], limit=1) or \
        Office.create({'name': 'ГУ ДПС у м. Києві', 'code': '2650'})
    company.write({
        'edrpou': company.edrpou or '12345678',
        'l10n_ua_tax_office_id': office.id,
        'l10n_ua_vat_signer_name': 'Олена КОВАЛЬ',
        'l10n_ua_vat_signer_rnokpp': '3124567896',
    })
