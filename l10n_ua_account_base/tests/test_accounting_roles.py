"""Accounting roles on the user form without developer mode — issue #567, part 1.

Category «Бухгалтерія (UA)»: 5 sections × 3 levels (Read Own → Read All →
Manage), 2 separate rights (submit to DPS, send payments to bank) and the
legacy 4 UA groups as «Роль (UA)». Old groups imply the new levels, and
existing users' rights must not change. Record rules are part 2+.
"""

from odoo.tests import TransactionCase, tagged

MOD = 'l10n_ua_account_base'
SECTIONS = ('vat', 'payroll', 'tax', 'invoice', 'bank')
LEVELS = ('own', 'all', 'manager')
EXTRA = ('dps_submit', 'bank_send')


@tagged('post_install', '-at_install')
class TestAccountingRoles(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.category = ref(f'{MOD}.module_category_l10n_ua_accounting_roles')
        cls.g = {
            f'{s}_{lvl}': ref(f'{MOD}.group_ua_{s}_{lvl}')
            for s in SECTIONS for lvl in LEVELS
        }
        for e in EXTRA:
            cls.g[e] = ref(f'{MOD}.group_ua_{e}')
        cls.ua_user = ref(f'{MOD}.group_ua_user')
        cls.ua_accountant = ref(f'{MOD}.group_ua_accountant')
        cls.ua_tax_accountant = ref(f'{MOD}.group_ua_tax_accountant')
        cls.ua_manager = ref(f'{MOD}.group_ua_manager')
        cls.old_groups = cls.ua_user | cls.ua_accountant | cls.ua_tax_accountant | cls.ua_manager
        cls.new_groups = cls.env['res.groups'].union(*cls.g.values())

    def _implies(self, group, *keys):
        return all(self.g[k] in group.all_implied_ids for k in keys)

    # --- Criterion 1: what the user form shows ---------------------------

    def test_category_privileges_visible_without_debug(self):
        """Every new group and old UA group has a privilege in the new
        category, so the form renders it as a selection outside debug mode."""
        privileges = self.category.privilege_ids
        self.assertEqual(len(privileges), 8, "Role + 5 sections + 2 extra rights")
        for group in self.new_groups | self.old_groups:
            self.assertEqual(group.privilege_id.category_id, self.category, group.name)

        hierarchy = self.env['res.groups']._get_view_group_hierarchy()
        cat = next(c for c in hierarchy['categories'] if c['id'] == self.category.id)
        self.assertEqual(len(cat['privilege_ids']), 8)

    def test_section_levels_are_ordered_chain(self):
        hierarchy = self.env['res.groups']._get_view_group_hierarchy()
        for s in SECTIONS:
            chain = [self.g[f'{s}_{lvl}'] for lvl in LEVELS]
            privilege = chain[0].privilege_id
            self.assertEqual(
                hierarchy['privileges'][privilege.id]['group_ids'],
                [grp.id for grp in chain], f"{s}: Read Own → Read All → Manage")
            self.assertTrue(self._implies(chain[2], f'{s}_all', f'{s}_own'))
            self.assertTrue(self._implies(chain[1], f'{s}_own'))
            self.assertNotIn(chain[2], chain[0].all_implied_ids)

    def test_role_privilege_keeps_old_order(self):
        hierarchy = self.env['res.groups']._get_view_group_hierarchy()
        privilege = self.ua_user.privilege_id
        self.assertEqual(
            hierarchy['privileges'][privilege.id]['group_ids'],
            [self.ua_user.id, self.ua_accountant.id, self.ua_tax_accountant.id, self.ua_manager.id])

    def test_ukrainian_labels(self):
        self.env['res.lang']._activate_lang('uk_UA')
        self.env['ir.module.module']._load_module_terms([MOD], ['uk_UA'], overwrite=True)
        env_uk = self.env(context=dict(self.env.context, lang='uk_UA'))
        self.assertEqual(env_uk.ref(f'{MOD}.module_category_l10n_ua_accounting_roles').name,
                         'Бухгалтерія (UA)')
        names = env_uk['res.groups.privilege'].browse(self.category.privilege_ids.ids).mapped('name')
        for expected in ('ПДВ і ПН', 'Зарплата', 'Податки', 'Рахунки', 'Банки',
                         'Подання в ДПС', 'Відправка платежів у банк', 'Роль (UA)'):
            self.assertIn(expected, names)
        levels = env_uk['res.groups'].browse(
            [self.g[f'vat_{lvl}'].id for lvl in LEVELS]).mapped('name')
        self.assertEqual(levels, ['Обмежено читати', 'Читати всі', 'Керувати'])

    # --- Criterion 2: standard Accounting section untouched --------------

    def test_standard_accounting_privilege_untouched(self):
        std = self.env.ref('account.res_groups_privilege_accounting')
        ours = std.group_ids.filtered(
            lambda grp: grp.get_external_id().get(grp.id, '').startswith(MOD + '.'))
        self.assertFalse(ours)
        self.assertNotEqual(std.category_id, self.category)

    # --- Mapping old groups → new levels (criteria 14, 15) ---------------

    def test_old_accountant_mapping(self):
        acc = self.ua_accountant
        self.assertTrue(self._implies(
            acc, 'invoice_manager', 'bank_manager', 'vat_all', 'tax_all', 'payroll_all'))
        for k in ('vat_manager', 'tax_manager', 'payroll_manager', 'dps_submit', 'bank_send'):
            self.assertNotIn(self.g[k], acc.all_implied_ids, k)

    def test_old_tax_accountant_mapping(self):
        tax = self.ua_tax_accountant
        self.assertTrue(self._implies(tax, 'vat_manager', 'tax_manager', 'dps_submit'))
        for k in ('payroll_manager', 'bank_send'):
            self.assertNotIn(self.g[k], tax.all_implied_ids, k)

    def test_chief_accountant_has_everything(self):
        for key, group in self.g.items():
            self.assertIn(group, self.ua_manager.all_implied_ids, key)

    def test_admin_has_extra_rights(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group(f'{MOD}.group_ua_dps_submit'))
        self.assertTrue(admin.has_group(f'{MOD}.group_ua_bank_send'))
        for s in SECTIONS:
            self.assertTrue(admin.has_group(f'{MOD}.group_ua_{s}_manager'), s)

    def test_new_levels_do_not_widen_old_groups(self):
        """Standard (non-UA) groups reached through any new level are already
        held by UA Accountant — so old users' rights do not change."""
        for key, group in self.g.items():
            extra = (group.all_implied_ids - self.new_groups) - self.ua_accountant.all_implied_ids
            self.assertFalse(extra, f"{key} adds {extra.mapped('name')}")

    def test_new_levels_do_not_imply_old_groups(self):
        """Р3: no new level gives UA Accountant (OSV, journal orders, all entries)."""
        for key, group in self.g.items():
            self.assertFalse(group.all_implied_ids & self.old_groups, key)

    def test_extra_rights_not_part_of_manage(self):
        """Р4 (16.11): manage level alone gives neither DPS submit nor bank send."""
        for s in SECTIONS:
            implied = self.g[f'{s}_manager'].all_implied_ids
            for e in EXTRA:
                self.assertNotIn(self.g[e], implied, f'{s}_manager → {e}')

    def test_old_user_rights_unchanged(self):
        user = self.env['res.users'].create({
            'name': 'UA accountant (roles test)', 'login': 'ua_roles_old_acc',
            'group_ids': [(6, 0, [self.ua_accountant.id])],
        })
        self.assertTrue(user.has_group('account.group_account_user'))
        self.assertTrue(user.has_group(f'{MOD}.group_ua_invoice_manager'))
        self.assertTrue(user.has_group(f'{MOD}.group_ua_bank_manager'))
        self.assertFalse(user.has_group(f'{MOD}.group_ua_dps_submit'))
        self.assertFalse(user.has_group('account.group_account_manager'))

    def test_assign_level_on_user(self):
        user = self.env['res.users'].create({
            'name': 'Invoice clerk (roles test)', 'login': 'ua_roles_invoice',
            'group_ids': [(6, 0, [self.g['invoice_manager'].id])],
        })
        self.assertTrue(user.has_group('account.group_account_invoice'))
        self.assertTrue(user.has_group(f'{MOD}.group_ua_invoice_own'))
        self.assertFalse(user.has_group(f'{MOD}.group_ua_accountant'))
        self.assertFalse(user.has_group('account.group_account_user'))
