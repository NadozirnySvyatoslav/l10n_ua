from odoo import fields, models

# Where an accrual goes in form № 1-ПВ «Звіт із праці» (наказ Держстату
# від 15.04.2024 № 117), Section III «Склад фонду оплати праці». The structure
# follows the Інструкція зі статистики заробітної плати (наказ Мінпраці
# від 13.01.2004 № 5): основна (п. 2.1), додаткова (п. 2.2), заохочувальні та
# компенсаційні виплати (п. 2.3), and payments outside the wage fund (п. 3),
# such as benefits paid by the Social Insurance Fund and severance pay.
L10N_UA_1PV_GROUPS = [
    ('basic', 'Basic wage (5020)'),
    ('allowance', 'Additional: allowances and surcharges (5030, 5040)'),
    ('bonus', 'Additional: systematic bonuses (5030, 5050)'),
    ('indexation', 'Additional: indexation (5030, 5051)'),
    ('delay_compensation', 'Additional: compensation for late payment (5030, 5052)'),
    ('additional', 'Additional: other (5030)'),
    ('additional_unworked', 'Additional: pay for time not worked (5030, 5090)'),
    ('incentive', 'Incentive and compensation payments (5060)'),
    ('material_aid', 'Incentive: material aid (5060, 5070)'),
    ('social_benefit', 'Incentive: individual social benefits (5060, 5080)'),
    ('incentive_unworked', 'Incentive: pay for time not worked (5060, 5090)'),
    ('excluded', 'Not part of the wage fund'),
]

# The accrual types shipped by l10n_ua_hr_salary, by code. Read before the
# category, so that a database where this module was installed before the
# field existed still files them right without any data being written.
L10N_UA_1PV_GROUP_BY_CODE = {
    'SALARY': 'basic',
    'PIECE': 'basic',
    'ALLOWANCE': 'allowance',
    'SENIORITY': 'allowance',
    'NIGHT': 'allowance',
    'HOLIDAY': 'allowance',
    'OVERTIME': 'allowance',      # додаткова: оплата надурочної роботи
    'BONUS': 'bonus',
    'INDEXATION': 'indexation',
    'VACATION': 'additional_unworked',   # додаткова: оплата щорічних відпусток
    'COMP_VAC': 'additional',            # додаткова: компенсація невикористаної відпустки
    'RETRO': 'additional',
    'SICK_EMP': 'incentive_unworked',    # перші 5 днів непрацездатності за рахунок роботодавця
    'MAT_AID': 'material_aid',
    'INKIND': 'incentive',
    'SICK_FSS': 'excluded',              # допомога за рахунок ПФУ (до 2023 — ФСС) — поза ФОП
    'MATERNITY': 'excluded',
    'SEVERANCE': 'excluded',             # вихідна допомога — поза ФОП
}

L10N_UA_1PV_GROUP_BY_CATEGORY = {
    'wage': 'basic',
    'allowance': 'allowance',
    'bonus': 'bonus',
    'vacation': 'additional_unworked',
    'sick': 'excluded',
    'maternity': 'excluded',
    'compensation': 'incentive',
    'other': 'incentive',
}


class HrAccrualType(models.Model):
    _inherit = 'hr.accrual.type'

    l10n_ua_1pv_group = fields.Selection(
        L10N_UA_1PV_GROUPS,
        string='1-PV Wage Fund Row',
        help='Where this accrual is reported in Section III of the 1-PV '
             'labour report. Left empty, the standard types are filed by '
             'their code and any other type by its category.',
    )

    def _l10n_ua_1pv_effective_group(self):
        self.ensure_one()
        return (self.l10n_ua_1pv_group
                or L10N_UA_1PV_GROUP_BY_CODE.get(self.code)
                or L10N_UA_1PV_GROUP_BY_CATEGORY.get(self.category)
                or 'incentive')
