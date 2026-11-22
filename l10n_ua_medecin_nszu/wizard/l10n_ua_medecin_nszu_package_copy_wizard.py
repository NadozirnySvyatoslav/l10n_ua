from odoo import _, api, fields, models
from odoo.exceptions import UserError


class L10nUaMedecinNszuPackageCopyWizard(models.TransientModel):
    """Copy a year's НСЗУ packages to another year.

    The ПМГ is approved every year, mostly with the same set of packages and
    new tariffs. The wizard duplicates the packages (the year in the code is
    replaced, e.g. PMD-2026 -> PMD-2027), optionally keeps the tariffs and marks
    them as "to be confirmed" until they are checked against the new ПМГ.
    Packages that already exist in the target year are skipped, so the wizard
    can be run repeatedly.
    """
    _name = 'l10n_ua.medecin.nszu.package.copy.wizard'
    _description = 'Копіювання пакетів НСЗУ на інший рік'

    source_year = fields.Integer(string='З року', required=True,
                                 default=lambda self: self._default_source_year())
    target_year = fields.Integer(string='На рік', required=True,
                                 default=lambda self: self._default_source_year() + 1)
    package_ids = fields.Many2many(
        'l10n_ua.medecin.nszu.package', 'l10n_ua_nszu_pkg_copy_wizard_rel',
        'wizard_id', 'package_id', string='Пакети',
        help='Якщо порожньо — копіюються всі активні пакети року-джерела.')
    keep_tariff = fields.Boolean(
        string='Зберегти тарифи', default=True,
        help='Перенести базові тарифи як відправну точку. Інакше тариф буде порожній.')
    mark_to_confirm = fields.Boolean(
        string='Позначити тарифи як «потребує підтвердження»', default=True)

    @api.model
    def _default_source_year(self):
        packages = self._context_packages()
        if packages:
            return max(packages.mapped('year'))
        last = self.env['l10n_ua.medecin.nszu.package'].search([], order='year desc', limit=1)
        return last.year or fields.Date.context_today(self).year

    @api.model
    def _context_packages(self):
        if self.env.context.get('active_model') == 'l10n_ua.medecin.nszu.package':
            return self.env['l10n_ua.medecin.nszu.package'].browse(
                self.env.context.get('active_ids') or []).exists()
        return self.env['l10n_ua.medecin.nszu.package']

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        packages = self._context_packages()
        if packages and 'package_ids' in fields_list:
            res['package_ids'] = [(6, 0, packages.ids)]
        return res

    @api.model
    def _target_code(self, code, source_year, target_year):
        src, dst = str(source_year), str(target_year)
        return code.replace(src, dst) if src in code else code

    def _get_source_packages(self):
        self.ensure_one()
        if self.package_ids:
            return self.package_ids.filtered(lambda p: p.year == self.source_year)
        return self.env['l10n_ua.medecin.nszu.package'].search([
            ('year', '=', self.source_year), ('is_active', '=', True),
        ])

    def _copy_packages(self):
        """Create the target-year packages; return them (existing ones are skipped)."""
        self.ensure_one()
        if self.target_year == self.source_year:
            raise UserError(_('Рік призначення має відрізнятися від року-джерела.'))
        Package = self.env['l10n_ua.medecin.nszu.package']
        sources = self._get_source_packages()
        if not sources:
            raise UserError(_('Немає пакетів %s року для копіювання.', self.source_year))
        new_packages = Package
        for package in sources:
            code = self._target_code(package.code, self.source_year, self.target_year)
            if Package.search_count([('code', '=', code), ('year', '=', self.target_year)]):
                continue
            new_packages |= package.copy({
                'code': code,
                'name': package.name,  # no "(copy)" suffix
                'year': self.target_year,
                'base_tariff': package.base_tariff if self.keep_tariff else 0.0,
                'tariff_to_confirm': self.mark_to_confirm or package.tariff_to_confirm,
                'is_active': True,
            })
        return new_packages

    def action_copy(self):
        self.ensure_one()
        self._copy_packages()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Пакети НСЗУ %s', self.target_year),
            'res_model': 'l10n_ua.medecin.nszu.package',
            'view_mode': 'list,form',
            'domain': [('year', '=', self.target_year)],
        }
