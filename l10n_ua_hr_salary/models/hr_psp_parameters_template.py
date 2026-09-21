from odoo import models, fields


class HrPspParametersTemplate(models.Model):
    """Statutory payroll parameters shipped with the module.

    A reference loaded from data/hr_psp_parameters_data.xml. It belongs to no
    company and is never used in a computation: every company gets its own
    `hr.psp.parameters` records created from it, and from then on the
    company's administrator manages them independently.
    """
    _name = 'hr.psp.parameters.template'
    _description = 'Statutory PSP Parameters'
    _order = 'date_from'

    year = fields.Integer(string='Year', required=True)
    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To')
    subsistence_minimum = fields.Float(string='Subsistence Minimum', required=True)
    min_wage = fields.Float(string='Minimum Wage', required=True)
    min_hourly_wage = fields.Float(string='Minimum Hourly Wage', required=True)
    pdfo_rate = fields.Float(string='PDFO Rate (%)', default=18.0)
    military_tax_rate = fields.Float(string='Military Tax Rate (%)', default=5.0)
    esv_rate = fields.Float(string='ESV Rate (%)', default=22.0)

    _unique_date_from = models.Constraint(
        'unique(date_from)',
        'Statutory parameters for this period already exist!',
    )

    def _company_values(self, company):
        self.ensure_one()
        return {
            'year': self.year,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'subsistence_minimum': self.subsistence_minimum,
            'min_wage': self.min_wage,
            'min_hourly_wage': self.min_hourly_wage,
            'pdfo_rate': self.pdfo_rate,
            'military_tax_rate': self.military_tax_rate,
            'esv_rate': self.esv_rate,
            'company_id': company.id,
        }
