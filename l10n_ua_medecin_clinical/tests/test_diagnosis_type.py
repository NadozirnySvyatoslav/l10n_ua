"""Типізовані діагнози, зворотна сумісність is_primary — issue #225."""
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosisType(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env['res.partner'].create({'name': 'Шевченко Ірина'})
        cls.patient = cls.env['l10n_ua.medecin.patient'].create({
            'partner_id': partner.id, 'company_id': cls.env.company.id})
        cls.doctor = cls.env['hr.employee'].create({'name': 'Лікар Андрій'})
        cls.encounter = cls.env['l10n_ua.medecin.encounter'].create({
            'patient_id': cls.patient.id,
            'doctor_id': cls.doctor.id,
            'date_start': datetime(2026, 4, 1, 9, 0),
        })
        cls.icd10 = cls.env['l10n_ua.medecin.icd10'].search(
            [('is_selectable', '=', True)], limit=1)
        cls.Diagnosis = cls.env['l10n_ua.medecin.diagnosis']

    def _diag(self, **vals):
        return self.Diagnosis.create(dict(
            {'encounter_id': self.encounter.id, 'icd10_id': self.icd10.id}, **vals))

    def test_default_type_and_owner_fields(self):
        diag = self._diag()
        self.assertEqual(diag.diagnosis_type, 'clinical')
        self.assertFalse(diag.is_primary)
        self.assertEqual(diag.patient_id, self.patient)
        self.assertEqual(diag.doctor_id, self.doctor)
        self.assertEqual(diag.date_start, self.encounter.date_start)
        self.assertEqual(diag.company_id, self.encounter.company_id)
        self.assertTrue(diag.date_established)

    def test_is_primary_legacy_create(self):
        """Старий код, що пише is_primary=True, отримує заключний діагноз."""
        diag = self._diag(is_primary=True)
        self.assertEqual(diag.diagnosis_type, 'final')
        self.assertTrue(diag.is_primary)

    def test_is_primary_follows_type(self):
        diag = self._diag(diagnosis_type='final')
        self.assertTrue(diag.is_primary)
        self.assertEqual(self.Diagnosis.search(
            [('is_primary', '=', True), ('id', '=', diag.id)]), diag)
        diag.diagnosis_type = 'concomitant'
        self.assertFalse(diag.is_primary)
        diag.is_primary = True
        self.assertEqual(diag.diagnosis_type, 'final')
        diag.is_primary = False
        self.assertEqual(diag.diagnosis_type, 'clinical')

    def test_owner_required(self):
        with self.assertRaises(ValidationError):
            self.Diagnosis.create({'icd10_id': self.icd10.id})

    def test_first_detected(self):
        diag = self._diag(is_first_detected=True, date_established='2026-04-01')
        self.assertTrue(diag.is_first_detected)
        self.assertEqual(str(diag.date_established), '2026-04-01')
