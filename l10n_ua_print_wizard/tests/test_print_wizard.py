from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPrintWizard(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.invoice = cls.init_invoice('out_invoice', products=cls.product_a, post=True)

    def _wizard(self):
        return self.env['l10n_ua.print.wizard'].create({'move_ids': [(6, 0, self.invoice.ids)]})

    def test_lists_print_menu_reports(self):
        wizard = self._wizard()
        bound = self.env['ir.actions.actions'].get_bindings('account.move').get('report', [])
        self.assertTrue(set(wizard.available_report_ids.ids) <= {b['id'] for b in bound})
        self.assertIn(self.env.ref('account.account_invoices'), wizard.available_report_ids)

    def test_default_report_preselected(self):
        default = self.env['account.move.send']._get_default_pdf_report_id(self.invoice)
        self.assertEqual(self._wizard().report_id, default)

    def test_default_kept_when_list_read_first(self):
        """The Print button reads the list before the selection."""
        default = self.env['account.move.send']._get_default_pdf_report_id(self.invoice)
        action = self.invoice.action_print_pdf()
        self.assertEqual(action.get('res_model'), 'l10n_ua.print.wizard')
        wizard = self.env['l10n_ua.print.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.report_id, default)

    def test_print_button_opens_wizard(self):
        self.assertGreater(len(self._wizard().available_report_ids), 1)
        action = self.invoice.action_print_pdf()
        self.assertEqual(action['res_model'], 'l10n_ua.print.wizard')

    def test_internal_user_can_open_wizard(self):
        """Users who see invoices through other apps (e.g. sales) must keep the Print button."""
        user = self.env['res.users'].create({
            'name': 'Plain internal user',
            'login': 'print_wizard_plain_user',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        self.assertTrue(self.env['l10n_ua.print.wizard'].with_user(user).has_access('create'))

    def test_print_chosen_report(self):
        wizard = self._wizard()
        report = self.env.ref('account.account_invoices_without_payment')
        wizard.report_id = report
        action = wizard.with_context(discard_logo_check=True).action_print()
        self.assertEqual(action['report_name'], report.report_name)
        self.assertTrue(action['close_on_report_download'])
