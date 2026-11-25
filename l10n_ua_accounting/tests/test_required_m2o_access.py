"""Fitness-тест прав: обовʼязкові Many2one читаються тими, хто бачить модель.

#694: закриття періоду було доступне бухгалтеру, а його обовʼязковий
`period_id` (l10n_ua.tax.period) — лише податковому бухгалтеру, тож форма
падала з AccessError. Тест ловить увесь клас таких розривів у моделях
l10n_ua_*: група, яка має read на модель, має мати read і на comodel
кожного обовʼязкового Many2one (своїм правом, успадкованим або глобальним).
"""

import re

from odoo.tests import TransactionCase, tagged

ADR_REF = re.compile(r'ADR \d{4}')

# Розриви, що були до #694: кожен прибирається окремою issue і зникає звідси.
# Значення — посилання на ADR (перевіряє test_entries_reference_adr).
KNOWN_GAPS = {
    ('l10n_ua.vat.declaration', 'period_id', 'account.group_account_manager'): '#702, ADR 0005',
    ('l10n_ua.vat.register', 'period_id', 'account.group_account_manager'): '#702, ADR 0005',
}

# Свідомо дозволені «розриви»: ACL на comodel немає, але процес працює
# (сценарій покрито окремим тестом).
ALLOWED = {
    # Odoo віддає користувачу без HR-прав публічні поля працівника;
    # read на hr.employee (персональні дані) бухгалтеру не даємо.
    # Сценарій — test_advance_report_access.
    ('l10n_ua.advance.report', 'employee_id', 'account.group_account_user'): '#700, ADR 0005',
}


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestRequiredMany2oneAccess(TransactionCase):

    def _readers(self, model_name):
        """Групи з read на модель; None у множині — глобальне право."""
        rules = self.env['ir.model.access'].sudo().search([
            ('model_id.model', '=', model_name), ('perm_read', '=', True)])
        return {rule.group_id.id or None for rule in rules}

    def _ref_key(self, entry):
        model, field, xmlid = entry
        group = self.env.ref(xmlid, raise_if_not_found=False)
        if group is None or self.env.get(model) is None:
            return None  # модуль запису не встановлено
        return (model, field, group.id)

    def _gaps(self):
        """Усі розриви як {(модель, поле, id групи): опис}."""
        Groups = self.env['res.groups'].sudo()
        models = self.env['ir.model'].sudo().search([('transient', '=', False)])
        gaps = {}
        for ir_model in models:
            if not ir_model.model.startswith('l10n_ua.'):
                continue
            Model = self.env.get(ir_model.model)
            if Model is None or Model._abstract:
                continue
            readers = self._readers(ir_model.model) - {None}
            for field in Model._fields.values():
                if field.type != 'many2one' or not field.required or not field.store:
                    continue
                comodel_readers = self._readers(field.comodel_name)
                if None in comodel_readers:
                    continue
                for group in Groups.browse(sorted(readers)):
                    if not (comodel_readers & set((group | group.all_implied_ids).ids)):
                        gaps[(ir_model.model, field.name, group.id)] = (
                            f'{ir_model.model}.{field.name} -> {field.comodel_name}: '
                            f'{group.full_name}')
        return gaps

    def test_entries_reference_adr(self):
        """Кожен запис KNOWN_GAPS/ALLOWED має посилання на ADR (ADR 0005)."""
        bad = [f'{entry}: {ref!r}' for table in (KNOWN_GAPS, ALLOWED)
               for entry, ref in table.items() if not ADR_REF.search(ref or '')]
        self.assertFalse(bad, 'Entries without ADR reference:\n' + '\n'.join(bad))
        self.assertFalse(set(KNOWN_GAPS) & set(ALLOWED),
                         'Entry is both a known gap and allowed')

    def test_required_many2one_readable(self):
        gaps = self._gaps()
        listed = {}
        for table in (KNOWN_GAPS, ALLOWED):
            for entry in table:
                key = self._ref_key(entry)
                if key:
                    listed[key] = entry
        unexpected = [desc for key, desc in gaps.items() if key not in listed]
        self.assertFalse(unexpected, 'Required Many2one unreadable for model readers:\n'
                         + '\n'.join(sorted(unexpected)))
        # Закритий розрив має зникнути зі списку, щоб не ховати повернення.
        stale = [str(entry) for key, entry in listed.items() if key not in gaps]
        self.assertFalse(stale, 'Gap is closed, remove the entry:\n' + '\n'.join(sorted(stale)))
