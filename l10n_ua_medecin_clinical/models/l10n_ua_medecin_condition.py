from odoo import fields, models


class L10nUaMedecinCondition(models.Model):
    """Хронічний стан / поточний діагноз пацієнта (загальний health summary)."""
    _name = 'l10n_ua.medecin.condition'
    _description = 'Стан здоров\'я пацієнта'
    _order = 'date_onset desc, patient_id'

    patient_id = fields.Many2one('l10n_ua.medecin.patient', required=True,
                                   ondelete='cascade', index=True)
    icd10_id = fields.Many2one('l10n_ua.medecin.icd10', string='МКХ-10', required=True,
                               domain=[('is_selectable', '=', True)])
    date_onset = fields.Date(string='Дата встановлення',
                              default=fields.Date.context_today)
    date_resolved = fields.Date(string='Дата зняття')
    is_chronic = fields.Boolean(string='Хронічний', default=True)
    severity = fields.Selection([
        ('mild', 'Легка'),
        ('moderate', 'Помірна'),
        ('severe', 'Тяжка'),
    ], string='Ступінь')
    note = fields.Text(string='Примітка')


class L10nUaMedecinAllergy(models.Model):
    _name = 'l10n_ua.medecin.allergy'
    _description = 'Алергія пацієнта'
    _order = 'patient_id, allergen'

    patient_id = fields.Many2one('l10n_ua.medecin.patient', required=True,
                                   ondelete='cascade', index=True)
    allergen = fields.Char(string='Алерген', required=True)
    severity = fields.Selection([
        ('mild', 'Легка'),
        ('moderate', 'Помірна'),
        ('severe', 'Тяжка / анафілаксія'),
    ], string='Тяжкість реакції', default='mild')
    reaction = fields.Char(string='Реакція', help='Кропивниця, набряк, шок тощо')
    note = fields.Text(string='Примітка')
