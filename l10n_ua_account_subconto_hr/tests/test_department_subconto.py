"""HR department works as a subconto dimension once the bridge is installed — issue #182."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDepartmentSubconto(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({'name': 'Бухгалтерія'})

        cls.account = cls.env['account.account'].create({
            'name': 'Test Subconto Account',
            'code': 'SUBC01',
            'account_type': 'asset_current',
            'company_ids': [(4, cls.env.company.id)],
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'Subconto Misc',
            'code': 'SBMSC',
            'type': 'general',
            'company_id': cls.env.company.id,
        })
        cls.move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': cls.journal.id,
            'line_ids': [
                (0, 0, {'account_id': cls.account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.line = cls.move.line_ids[0]

    def test_subconto_type_exists(self):
        """The bridge ships the l10n_ua.subconto.type record the base module lacked."""
        subconto_type = self.env.ref(
            'l10n_ua_account_subconto_hr.subconto_type_department')
        self.assertEqual(subconto_type.model_name, 'hr.department')

    def test_selection_extended_by_bridge(self):
        """#701: the bridge extends _selection_subconto_models, not replaces it."""
        models = dict(self.env['l10n_ua.subconto.type']._selection_subconto_models())
        self.assertIn('hr.department', models)
        self.assertIn('res.partner', models)

    def test_quick_fields_map_includes_department(self):
        """The base map is extended, not replaced."""
        mapping = self.env['account.move.line']._subconto_quick_fields_map()
        self.assertEqual(mapping.get('hr.department'), 'subconto_department_id')
        self.assertEqual(mapping.get('res.partner'), 'subconto_partner_id')
        self.assertEqual(mapping.get('product.product'), 'subconto_product_id')

    def test_writing_quick_field_creates_subconto_value(self):
        """The #182 regression: the inverse silently did nothing (no subconto type)."""
        self.line.subconto_department_id = self.department

        subconto = self.line.subconto_ids.filtered(
            lambda s: s.res_model == 'hr.department')
        self.assertTrue(subconto, 'Writing the quick field must create a subconto value')
        self.assertEqual(subconto.res_id, self.department.id)

    def test_quick_field_recomputes_from_subconto_value(self):
        self.line.subconto_department_id = self.department
        self.line.invalidate_recordset(['subconto_department_id'])
        self.assertEqual(self.line.subconto_department_id, self.department)

    def test_other_quick_fields_still_work(self):
        """Extending the map must not break the fields the base module owns."""
        partner = self.env['res.partner'].create({'name': 'Субконто Контрагент'})
        self.line.subconto_partner_id = partner

        subconto = self.line.subconto_ids.filtered(
            lambda s: s.res_model == 'res.partner')
        self.assertTrue(subconto)
        self.assertEqual(self.line.subconto_partner_id, partner)
