"""Tests for issue #634: ПМГ-2026 packages and copying packages to a new year."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_medecin_nszu')
class TestNszuPackageYears(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Package = cls.env['l10n_ua.medecin.nszu.package']
        cls.Wizard = cls.env['l10n_ua.medecin.nszu.package.copy.wizard']

    def test_2025_packages_kept(self):
        codes = set(self.Package.search([('year', '=', 2025)]).mapped('code'))
        self.assertTrue({'PMD-2025', 'EMD-2025', 'CB-2025', 'SPEC-AMB-2025',
                         'HOSP-2025'} <= codes)

    def test_2026_packages_loaded(self):
        pmd = self.env.ref('l10n_ua_medecin_nszu.package_pmd_capitation_2026')
        self.assertEqual((pmd.code, pmd.year), ('PMD-2026', 2026))
        self.assertAlmostEqual(pmd.base_tariff, 1007.3)
        self.assertFalse(pmd.tariff_to_confirm)
        emd = self.env.ref('l10n_ua_medecin_nszu.package_emd_2026')
        self.assertAlmostEqual(emd.base_tariff, 375.0)
        for xmlid in ('package_childbirth_2026', 'package_specialized_2026',
                      'package_hospital_2026'):
            package = self.env.ref(f'l10n_ua_medecin_nszu.{xmlid}')
            self.assertEqual(package.year, 2026)
            self.assertTrue(package.tariff_to_confirm,
                            f'{package.code}: unverified tariff must be flagged')
        # every 2025 package type has a 2026 counterpart
        types_2025 = set(self.Package.search([('year', '=', 2025)]).mapped('package_type'))
        types_2026 = set(self.Package.search([('year', '=', 2026)]).mapped('package_type'))
        self.assertTrue(types_2025 <= types_2026)

    def test_contract_line_takes_2026_tariff(self):
        contract = self.env['l10n_ua.medecin.nszu.contract'].create({
            'date_start': '2026-01-01', 'date_end': '2026-12-31',
        })
        line = self.env['l10n_ua.medecin.nszu.contract.line'].new({
            'contract_id': contract.id,
            'package_id': self.env.ref('l10n_ua_medecin_nszu.package_pmd_capitation_2026').id,
        })
        line._onchange_package()
        self.assertAlmostEqual(line.tariff, 1007.3)

    def test_copy_year_to_next(self):
        wizard = self.Wizard.create({'source_year': 2026, 'target_year': 2027})
        new_packages = wizard._copy_packages()
        sources = self.Package.search([('year', '=', 2026), ('is_active', '=', True)])
        self.assertEqual(len(new_packages), len(sources))
        self.assertEqual(set(new_packages.mapped('year')), {2027})
        pmd = new_packages.filtered(lambda p: p.code == 'PMD-2027')
        self.assertTrue(pmd)
        self.assertEqual(pmd.name, 'Первинна медична допомога (капітація)')
        self.assertAlmostEqual(pmd.base_tariff, 1007.3)
        self.assertTrue(all(new_packages.mapped('tariff_to_confirm')))
        # sources untouched
        self.assertFalse(self.env.ref(
            'l10n_ua_medecin_nszu.package_pmd_capitation_2026').tariff_to_confirm)
        # second run is idempotent
        again = self.Wizard.create({'source_year': 2026, 'target_year': 2027})
        self.assertFalse(again._copy_packages())
        action = again.action_copy()
        self.assertEqual(action['domain'], [('year', '=', 2027)])

    def test_copy_selected_without_tariff(self):
        pmd = self.env.ref('l10n_ua_medecin_nszu.package_pmd_capitation_2026')
        custom = self.Package.create({
            'code': 'LOCAL', 'name': 'Пакет без року в коді',
            'package_type': 'other', 'year': 2026, 'base_tariff': 10,
        })
        wizard = self.Wizard.with_context(
            active_model=self.Package._name, active_ids=[pmd.id, custom.id],
        ).create({'keep_tariff': False, 'mark_to_confirm': False})
        self.assertEqual((wizard.source_year, wizard.target_year), (2026, 2027))
        self.assertEqual(wizard.package_ids, pmd | custom)
        new_packages = wizard._copy_packages()
        self.assertEqual(sorted(new_packages.mapped('code')), ['LOCAL', 'PMD-2027'])
        self.assertEqual(set(new_packages.mapped('base_tariff')), {0.0})
        self.assertFalse(any(new_packages.mapped('tariff_to_confirm')))

    def test_copy_errors(self):
        with self.assertRaises(UserError):
            self.Wizard.create({'source_year': 2026, 'target_year': 2026})._copy_packages()
        with self.assertRaises(UserError):
            self.Wizard.create({'source_year': 1999, 'target_year': 2000})._copy_packages()

    def test_open_wizard_action(self):
        pmd = self.env.ref('l10n_ua_medecin_nszu.package_pmd_capitation_2026')
        action = pmd.action_open_copy_wizard()
        self.assertEqual(action['res_model'], self.Wizard._name)
        self.assertEqual(action['context']['active_ids'], [pmd.id])
