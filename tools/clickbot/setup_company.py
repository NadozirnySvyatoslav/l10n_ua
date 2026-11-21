# Run through ``odoo shell`` on a fresh database, before ``account`` is
# installed: makes the main company Ukrainian (country UA, currency UAH), so
# that account installs the l10n_ua chart and the UA modules behave as on a
# real Ukrainian database.  ``env`` is provided by the shell.
ua, uah = env.ref('base.ua'), env.ref('base.UAH')  # noqa: F821
uah.active = True
company = env.ref('base.main_company')  # noqa: F821
company.write({'country_id': ua.id, 'currency_id': uah.id})
env.cr.commit()  # noqa: F821
print('clickbot company:', company.name, company.country_id.code, company.currency_id.name)
