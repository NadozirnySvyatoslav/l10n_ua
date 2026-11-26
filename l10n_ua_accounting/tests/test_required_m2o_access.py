"""Fitness-тест прав: обовʼязкові Many2one читаються тими, хто бачить модель.

#694: закриття періоду було доступне бухгалтеру, а його обовʼязковий
`period_id` (l10n_ua.tax.period) — лише податковому бухгалтеру, тож форма
падала з AccessError. Тест ловить увесь клас таких розривів у моделях
l10n_ua_*: група, яка має read на модель, має мати read і на comodel
кожного обовʼязкового Many2one (своїм правом, успадкованим або глобальним).

Перевіряються лише моделі й права l10n_ua_accounting та його залежностей
(транзитивно), щоб результат не залежав від інших встановлених модулів:
їхні розриви має ловити їхній власний тест.
"""

from odoo.tests import TransactionCase, tagged

# Розриви, що були до #694; кожен прибрати окремою issue, нові сюди не додавати.
KNOWN_GAPS = {
    ('l10n_ua.advance.report', 'employee_id', 'account.group_account_user'),
    ('l10n_ua.subconto.type', 'model_id', 'l10n_ua_account_base.group_ua_user'),
    ('l10n_ua.subconto.type', 'model_id', 'l10n_ua_account_base.group_ua_manager'),
    # account.group_account_manager не успадковує group_account_user,
    # тож read на tax.period для group_account_user цей розрив не закриває.
    ('l10n_ua.vat.declaration', 'period_id', 'account.group_account_manager'),
    ('l10n_ua.vat.register', 'period_id', 'account.group_account_manager'),
}


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestRequiredMany2oneAccess(TransactionCase):

    MODULE = 'l10n_ua_accounting'

    def _scope_modules(self):
        """Модуль тесту і всі його залежності (транзитивно)."""
        Module = self.env['ir.module.module'].sudo()
        scope, todo = set(), [self.MODULE]
        while todo:
            name = todo.pop()
            if name in scope:
                continue
            scope.add(name)
            module = Module.search([('name', '=', name)], limit=1)
            todo.extend(module.dependencies_id.mapped('name'))
        return scope

    def _readers(self, model_name, modules=None):
        """Групи з read на модель; None у множині — глобальне право.

        Записи ir.access без групи в Odoo 20 — обмеження, а не право.
        modules — враховувати лише права, оголошені в цих модулях.
        """
        rules = self.env['ir.access'].sudo().search([
            ('model_id.model', '=', model_name), ('operation', 'like', 'r'),
            ('kind', '=', 'permission')])
        if modules is not None:
            xmlids = rules._get_external_ids()
            rules = rules.filtered(lambda r: any(
                xid.split('.', 1)[0] in modules for xid in xmlids.get(r.id, [])))
        return {rule.group_id.id or None for rule in rules}

    def test_required_many2one_readable(self):
        Groups = self.env['res.groups'].sudo()
        scope = self._scope_modules()
        models = self.env['ir.model'].sudo().search([('transient', '=', False)])
        gaps = []
        known = {(model, field, self.env.ref(xmlid, raise_if_not_found=False))
                 for model, field, xmlid in KNOWN_GAPS}
        for ir_model in models:
            if not ir_model.model.startswith('l10n_ua.'):
                continue
            Model = self.env.get(ir_model.model)
            if Model is None or Model._abstract or Model._original_module not in scope:
                continue
            readers = self._readers(ir_model.model, scope) - {None}
            for field in Model._fields.values():
                if field.type != 'many2one' or not field.required or not field.store:
                    continue
                if field._module and field._module not in scope:
                    continue
                comodel_readers = self._readers(field.comodel_name)
                if None in comodel_readers:
                    continue
                for group in Groups.browse(sorted(readers)):
                    if (ir_model.model, field.name, group) in known:
                        continue
                    if not (comodel_readers & set((group | group.all_implied_ids).ids)):
                        gaps.append(f'{ir_model.model}.{field.name} -> {field.comodel_name}: '
                                    f'{group.full_name}')
        self.assertFalse(gaps, 'Required Many2one unreadable for model readers:\n'
                         + '\n'.join(sorted(gaps)))
