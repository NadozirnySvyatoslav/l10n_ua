"""Distribution of the Ukrainian working schedules to companies.

The core ``res.company._create_resource_calendar()`` gives every company its
own default calendar. This applies the same pattern to the ten statutory
regimes from ``data/resource_calendar_ua_data.xml``: each company gets its own
copy of every schedule.

Copies rather than one shared record per database is a deliberate choice:
``resource.calendar`` has a single ``company_id``, so while a schedule is
shared it can only belong to one company, and changing that field silently
switches it for all the others. The price is 10 x N records, which have to be
edited per company whenever the labour law changes.
"""

from odoo import api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _l10n_ua_calendar_templates(self):
        """Return the UA schedule templates: archived, company-less records.

        They are looked up through the module's XML ids rather than a list of
        ``ua_code`` values: the list of schedules already lives in the data
        file, and a second copy in Python would drift from the first one on
        the next edit.
        """
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'l10n_ua_hr_contract'),
            ('model', '=', 'resource.calendar'),
        ])
        return self.env['resource.calendar'].with_context(
            active_test=False).browse(data.mapped('res_id')).exists()

    def _l10n_ua_create_resource_calendars(self):
        """Create the missing UA schedule copies for every company in ``self``.

        Idempotent: an existing copy is recognised by its ``ua_code`` within
        the company, so calling this again (module update, migration re-run)
        creates no duplicates.
        """
        templates = self._l10n_ua_calendar_templates().filtered('ua_code')
        if not templates:
            return
        Calendar = self.env['resource.calendar'].sudo()
        for company in self:
            # active_test=False on purpose: resource_calendar_ids hides
            # archived records, so a company that archived a schedule it does
            # not use would get a fresh duplicate on the next run.
            existing = set(company.sudo().with_context(
                active_test=False).resource_calendar_ids.mapped('ua_code'))
            for template in templates:
                if template.ua_code in existing:
                    continue
                copy = Calendar.browse(template.id).copy({
                    # active is copied from the template, so without an
                    # explicit value the copy would be born archived.
                    'active': True,
                    'company_id': company.id,
                    # hours_per_week is declared copy=False and its compute
                    # skips flexible schedules (shift cycles, summarized
                    # accounting) - without an explicit value those would end
                    # up with a zero weekly norm.
                    'hours_per_week': template.hours_per_week,
                })
                # Odoo 19 appended " (copy)" to the name in copy_data, after
                # merging the default, so it could not be passed through it;
                # Odoo 20 dropped that override, but pinning the name here
                # keeps the schedules identically named across companies.
                copy.name = template.name
                # resource.calendar.leave_ids is copy=False in Odoo 20, so a
                # company's copy would come without the public holidays and
                # corporate days off its template carries. They belong to the
                # calendar (their company_id is a stored compute over
                # calendar_id.company_id), so each company needs its own row.
                # `name` is passed explicitly: Odoo 20 appends " (copy)" to
                # any Char field called `name` when a record is duplicated.
                for leave in template.sudo().leave_ids:
                    leave.copy({'calendar_id': copy.id, 'name': leave.name})

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._l10n_ua_create_resource_calendars()
        return companies
