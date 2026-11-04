"""Діагнози епізоду стаціонару і хірургічні втручання — issue #225."""
from datetime import datetime

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'l10n_ua_medecin_inpatient')
class TestAdmissionDiagnosisProcedure(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        partner = cls.env['res.partner'].create({'name': 'Бондар Олена'})
        cls.patient = cls.env['l10n_ua.medecin.patient'].create({
            'partner_id': partner.id, 'company_id': cls.company.id})
        cls.doctor = cls.env['hr.employee'].create({
            'name': 'Хірург Тарас', 'company_id': cls.company.id})
        icd = cls.env['l10n_ua.medecin.icd10'].search(
            [('is_selectable', '=', True)], limit=2)
        cls.icd_a, cls.icd_b = icd[0], icd[1]
        cls.ptype = cls.env['l10n_ua.medecin.procedure.type'].create({
            'code': 'T-30571-00', 'name': 'Апендектомія (тест)'})
        cls.Diagnosis = cls.env['l10n_ua.medecin.diagnosis']
        cls.Procedure = cls.env['l10n_ua.medecin.procedure']

    def setUp(self):
        super().setUp()
        self.adm = self.env['l10n_ua.medecin.admission'].create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor.id,
            'company_id': self.company.id,
            'date_admission': datetime(2026, 5, 4, 8, 0),
        })
        self.adm.action_admit()

    def _diag(self, dtype, icd=None, **vals):
        return self.Diagnosis.create(dict({
            'admission_id': self.adm.id,
            'icd10_id': (icd or self.icd_a).id,
            'diagnosis_type': dtype,
        }, **vals))

    def _discharge(self):
        self.adm.write({
            'date_discharge': datetime(2026, 5, 9, 10, 0),
            'treatment_result': 'recovery', 'discharge_type': 'home'})
        self.adm.action_discharge()

    # --- Діагнози ---

    def test_owner_fields_from_admission(self):
        diag = self._diag('admission')
        self.assertFalse(diag.encounter_id)
        self.assertEqual(diag.patient_id, self.patient)
        self.assertEqual(diag.doctor_id, self.doctor)
        self.assertEqual(diag.date_start, self.adm.date_admission)
        self.assertEqual(diag.company_id, self.company)
        self.assertIn(diag, self.adm.diagnosis_ids)

    def test_exactly_one_owner(self):
        encounter = self.env['l10n_ua.medecin.encounter'].create({
            'patient_id': self.patient.id, 'doctor_id': self.doctor.id})
        with self.assertRaises(ValidationError):
            self._diag('clinical', encounter_id=encounter.id)
        with self.assertRaises(ValidationError):
            self.Diagnosis.create({'icd10_id': self.icd_a.id})

    def test_discharge_requires_final_diagnosis(self):
        self._diag('admission')
        self._diag('concomitant', self.icd_b)
        with self.assertRaises(ValidationError):
            self._discharge()
        self.assertEqual(self.adm.state, 'admitted')
        final = self._diag('final')
        self._discharge()
        self.assertEqual(self.adm.state, 'discharged')
        self.assertEqual(self.adm.final_diagnosis_id, final)
        self.assertEqual(self.adm.final_icd10_id, self.icd_a)

    def test_only_one_final_diagnosis(self):
        self._diag('final')
        with self.assertRaises(ValidationError):
            self._diag('final', self.icd_b)
        other = self._diag('complication', self.icd_b)
        with self.assertRaises(ValidationError):
            other.is_primary = True

    def test_discharged_keeps_final(self):
        final = self._diag('final')
        self._discharge()
        with self.assertRaises(ValidationError):
            final.diagnosis_type = 'clinical'
        with self.assertRaises(UserError):
            final.unlink()
        # Патолого-анатомічний діагноз можна додати й після виписки.
        self._diag('pathological', self.icd_b)
        # Після повернення на лікування заключний діагноз можна замінити.
        self.adm.action_reopen()
        final.unlink()
        self.assertFalse(self.adm.final_diagnosis_id)

    # --- Втручання ---

    def test_procedure_basics(self):
        proc = self.Procedure.create({
            'admission_id': self.adm.id,
            'procedure_type_id': self.ptype.id,
            'date': datetime(2026, 5, 5, 9, 0),
            'surgeon_id': self.doctor.id,
            'anesthesia_type': 'general',
            'is_emergency': True,
        })
        self.assertEqual(proc.name, self.ptype.name)
        self.assertEqual(proc.code, 'T-30571-00')
        self.assertEqual(proc.patient_id, self.patient)
        self.assertEqual(proc.company_id, self.company)
        self.assertEqual(self.adm.procedure_count, 1)
        self.assertIn('T-30571-00', self.ptype.display_name)
        self.assertEqual(
            self.env['l10n_ua.medecin.procedure.type'].name_search('30571')[0][0],
            self.ptype.id)

    def test_procedure_date_within_admission(self):
        with self.assertRaises(ValidationError):
            self.Procedure.create({
                'admission_id': self.adm.id,
                'procedure_type_id': self.ptype.id,
                'date': datetime(2026, 5, 1, 9, 0),
                'surgeon_id': self.doctor.id,
            })

    def test_procedure_type_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['l10n_ua.medecin.procedure.type'].create({
                'code': 'T-30571-00', 'name': 'Дубль'})
            self.env.flush_all()

    def test_procedure_rule_and_views(self):
        self.assertTrue(self.env.ref(
            'l10n_ua_medecin_inpatient.l10n_ua_medecin_procedure_company_rule')['global'])
        for xmlid in ('l10n_ua_medecin_inpatient.action_procedure',
                      'l10n_ua_medecin_inpatient.action_procedure_type',
                      'l10n_ua_medecin_inpatient.action_admission',
                      'l10n_ua_medecin_clinical.action_diagnosis'):
            action = self.env.ref(xmlid)
            modes = action.view_mode.split(',')
            res = self.env[action.res_model].get_views(
                [(False, m) for m in modes] + [(action.search_view_id.id, 'search')])
            for mode in modes:
                self.assertIn(mode, res['views'], f'{xmlid}: {mode}')
