"""Shared ground for the material report tests: one store, one product.

The report is built from done stock moves, so every test starts by
making some — `_move` is the whole of the fixture work — and then asks
the wizard for its rows.
"""

from odoo.tests import TransactionCase


class MaterialReportCase(TransactionCase):
    """The store, the product and the helpers every test needs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # For a company without a document layout `report_action` hands back
        # not the report but the dialog to configure that layout
        # (ir_actions_report.py:1182). That is Odoo's standard onboarding
        # behaviour, not a flaw of the report, so the test company is put into
        # the same state a real one works in — otherwise the printing tests
        # would depend on how lived-in the database is.
        cls.company.external_report_layout_id = cls.env.ref(
            'web.external_layout_standard')
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')
        cls.customer = cls.env.ref('stock.stock_location_customers')
        cls.category = cls.env['product.category'].create({
            'name': 'Construction Materials',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Cement M-400',
            'is_storable': True,
            'default_code': 'CEM400',
            'standard_price': 150.0,
            'categ_id': cls.category.id,
        })

    def _move(self, source, dest, qty, when, product=None, uom=None):
        """A done stock move, dated explicitly so it lands in the period."""
        product = product or self.product
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'uom_id': (uom or product.uom_id).id,
            'location_id': source.id,
            'location_dest_id': dest.id,
        })
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.quantity = qty
        move.picked = True
        move._action_done()
        move.move_line_ids.write({'date': when})
        return move

    def _rows(self, wizard, monthly=False):
        """Rows of a single granularity: the report materializes both at once.

        The collapsed ones (the default) feed the List and the form, the
        monthly ones the Pivot table. The views tell them apart by domain, the
        tests by this helper.
        """
        return wizard.line_ids.filtered(
            lambda line: line.is_monthly == monthly)

    def _wizard(self, **kwargs):
        vals = {
            'date_from': '2026-03-01',
            'date_to': '2026-03-31',
            'location_id': self.stock.id,
            'responsible_person': 'Storekeeper Ivanenko',
        }
        vals.update(kwargs)
        return self.env['l10n_ua.material.report.wizard'].create(vals)

    def _shelf(self, name):
        return self.env['stock.location'].create({
            'name': name,
            'usage': 'internal',
            'location_id': self.stock.id,
        })

    def _kyiv(self, wizard):
        """The report as a Kyiv reader sees it (UTC+3 in July)."""
        return wizard.with_context(tz='Europe/Kyiv')

