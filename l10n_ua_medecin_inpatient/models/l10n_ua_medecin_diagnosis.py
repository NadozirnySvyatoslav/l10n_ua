from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class L10nUaMedecinDiagnosis(models.Model):
    """Діагноз епізоду стаціонарного лікування (#225).

    Розширює діагноз з l10n_ua_medecin_clinical другим власником —
    епізодом стаціонару; пацієнт / лікар / дата / заклад беруться з того
    власника, який заповнено.
    """
    _inherit = 'l10n_ua.medecin.diagnosis'

    admission_id = fields.Many2one(
        'l10n_ua.medecin.admission', string='Епізод стаціонару',
        ondelete='cascade', index=True)

    @api.depends('encounter_id.patient_id', 'encounter_id.doctor_id',
                 'encounter_id.date_start', 'encounter_id.company_id',
                 'admission_id.patient_id', 'admission_id.doctor_id',
                 'admission_id.date_admission', 'admission_id.company_id')
    def _compute_owner_fields(self):
        with_admission = self.filtered(lambda d: d.admission_id and not d.encounter_id)
        for rec in with_admission:
            adm = rec.admission_id
            rec.patient_id = adm.patient_id
            rec.doctor_id = adm.doctor_id
            rec.date_start = adm.date_admission
            rec.company_id = adm.company_id
        super(L10nUaMedecinDiagnosis, self - with_admission)._compute_owner_fields()

    @api.model
    def _owner_field_names(self):
        return super()._owner_field_names() + ['admission_id']

    @api.constrains('encounter_id', 'admission_id', 'icd10_id')
    def _check_single_owner(self):
        return super()._check_single_owner()

    @api.constrains('admission_id', 'diagnosis_type')
    def _check_admission_final_diagnosis(self):
        self.admission_id._check_final_diagnosis()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_discharged_final(self):
        for rec in self:
            if rec.diagnosis_type == 'final' and rec.admission_id.state == 'discharged':
                raise UserError(_(
                    'Не можна видалити заключний діагноз виписаного епізоду %s. '
                    'Спершу поверніть епізод на лікування.', rec.admission_id.name))


class L10nUaMedecinAdmission(models.Model):
    """Діагнози та втручання епізоду стаціонару (#225)."""
    _inherit = 'l10n_ua.medecin.admission'

    diagnosis_ids = fields.One2many(
        'l10n_ua.medecin.diagnosis', 'admission_id', string='Діагнози')
    final_diagnosis_id = fields.Many2one(
        'l10n_ua.medecin.diagnosis', string='Заключний діагноз',
        compute='_compute_final_diagnosis', store=True, index=True,
        help='Заключний клінічний діагноз (основний) — вхід групувальника ДСГ.')
    final_icd10_id = fields.Many2one(
        related='final_diagnosis_id.icd10_id', store=True,
        string='Заключний діагноз (МКХ-10)')
    procedure_ids = fields.One2many(
        'l10n_ua.medecin.procedure', 'admission_id', string='Втручання')
    procedure_count = fields.Integer(
        string='Кількість втручань', compute='_compute_procedure_count')

    @api.depends('diagnosis_ids.diagnosis_type')
    def _compute_final_diagnosis(self):
        for rec in self:
            finals = rec.diagnosis_ids.filtered(lambda d: d.diagnosis_type == 'final')
            rec.final_diagnosis_id = finals[:1]

    @api.depends('procedure_ids')
    def _compute_procedure_count(self):
        for rec in self:
            rec.procedure_count = len(rec.procedure_ids)

    @api.constrains('state')
    def _check_final_diagnosis_on_state(self):
        self._check_final_diagnosis()

    def _check_final_diagnosis(self):
        """Не більше одного заключного діагнозу; у виписаного — рівно один."""
        for rec in self:
            finals = rec.diagnosis_ids.filtered(lambda d: d.diagnosis_type == 'final')
            if len(finals) > 1:
                raise ValidationError(_(
                    'Епізод %s може мати лише один заключний діагноз; '
                    'інші позначте як супутні або ускладнення.', rec.name))
            if rec.state == 'discharged' and not finals:
                raise ValidationError(_(
                    'Для виписки епізоду %s вкажіть заключний діагноз.', rec.name))
