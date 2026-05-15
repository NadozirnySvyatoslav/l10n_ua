import logging
from lxml import etree
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrOrderTemplateWizard(models.TransientModel):
    _name = 'hr.order.template.wizard'
    _description = 'HR Order Template Selection Wizard'

    order_id = fields.Many2one('hr.order', string='Order', required=True)
    order_type = fields.Selection([
        ('hiring', 'Hiring'),
        ('dismissal', 'Dismissal'),
        ('transfer', 'Transfer'),
        ('vacation', 'Vacation'),
        ('bonus', 'Bonus'),
        ('sick_leave', 'Sick Leave'),
        ('business_trip', 'Business Trip'),
        ('other', 'Other'),
    ], string='Order Type')

    template_id = fields.Many2one(
        'hr.order.template',
        string='Template',
        required=True,
        domain="[('order_type', '=', order_type), ('active', '=', True)]"
    )

    def action_apply_template(self):
        self.ensure_one()
        template = self.template_id
        order = self.order_id
        vals = {}

        # Prepare context for QWeb rendering
        render_context = self._get_render_context(order)

        if template.subject:
            vals['subject'] = self._render_qweb(template.subject, render_context)

        if template.body:
            vals['content'] = self._render_qweb(template.body, render_context)

        if vals:
            order.write(vals)

        return {'type': 'ir.actions.act_window_close'}

    def _get_render_context(self, order):
        """Prepare context dictionary for QWeb template rendering."""
        employee = order.employee_id
        company = order.company_id

        return {
            'o': order,
            'order': order,
            'employee': employee,
            'company': company,
            'department': order.department_id or (employee.department_id if employee else False),
            'job': order.job_id or (employee.job_id if employee else False),
            'director': company.director_id,
            'accountant': company.accountant_id,
            'format_date': self._format_date,
            'format_date_ua': self._format_date_ua,
            'month_name': self._get_month_name,
        }

    def _render_qweb(self, template_str, context):
        """Render template string using QWeb engine."""
        if not template_str:
            return ''

        try:
            # Wrap template in t element for QWeb
            qweb_template = f'<t>{template_str}</t>'
            # Parse as XML element
            template_element = etree.fromstring(qweb_template.encode('utf-8'))
            # Render using QWeb
            result = self.env['ir.qweb']._render(template_element, context)
            return str(result)
        except Exception as e:
            _logger.error(f"QWeb rendering failed: {e}")
            # Fallback: return template as-is if QWeb fails
            return template_str

    def _format_date(self, date_val, fmt='%d.%m.%Y'):
        """Format date helper for templates."""
        if date_val:
            return date_val.strftime(fmt)
        return '____________'

    def _format_date_ua(self, date_val):
        """Format date in Ukrainian style: "15" січня 2026 р."""
        if date_val:
            return f'"{date_val.day}" {self._get_month_name(date_val.month)} {date_val.year} р.'
        return '"___" ____________ 20__ р.'

    def _get_month_name(self, month):
        """Get Ukrainian month name in genitive case."""
        months = {
            1: 'січня', 2: 'лютого', 3: 'березня', 4: 'квітня',
            5: 'травня', 6: 'червня', 7: 'липня', 8: 'серпня',
            9: 'вересня', 10: 'жовтня', 11: 'листопада', 12: 'грудня'
        }
        return months.get(month, '____________')
