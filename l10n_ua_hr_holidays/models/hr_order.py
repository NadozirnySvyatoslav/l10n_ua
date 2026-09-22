from odoo import models, fields, api


class HrOrder(models.Model):
    """Vacation-order behaviour that needs the leave types this module adds.

    hr.order lives in l10n_ua_hr_documents, which cannot reach
    res.company.l10n_ua_default_leave_type_id or hr.sick.leave — the
    dependency runs the other way — so the default-type preselection and
    the sick-leave link are contributed here.
    """
    _inherit = 'hr.order'

    sick_leave_id = fields.Many2one(
        'hr.sick.leave',
        string='Sick Leave',
        ondelete='set null',
        copy=False,
        index=True,
        help='The sick leave certificate this order is issued for. Set when '
             'the order is created from the certificate\'s "New Order" button.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        # An order opened from a sick leave's "New Order" button carries the
        # certificate in the context; re-apply it the same way the vacation
        # flow re-applies default_leave_id, so navigating away from the unsaved
        # form and back cannot save an unlinked order.
        sick_leave_from_ctx = self.env.context.get('default_sick_leave_id')
        if sick_leave_from_ctx:
            for vals in vals_list:
                vals.setdefault('sick_leave_id', sick_leave_from_ctx)
        orders = super().create(vals_list)
        for order in orders:
            if order.sick_leave_id and not order.sick_leave_id.order_id:
                order.sick_leave_id.write({'order_id': order.id})
        return orders

    @api.onchange('order_type')
    def _onchange_order_type_default_leave_type(self):
        """Preselect the company's default vacation type as soon as the order
        becomes a vacation order, the same default the leave form applies.
        An explicit choice is never overwritten."""
        if self.order_type != 'vacation' or self.work_entry_type_id:
            return
        company = self.company_id or self.env.company
        if company.l10n_ua_default_leave_type_id:
            self.work_entry_type_id = company.l10n_ua_default_leave_type_id

