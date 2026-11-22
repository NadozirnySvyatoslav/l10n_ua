"""Regression tests for issue #633: the current doctor must not be tracked."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_medecin_patient')
class TestActiveDoctorTracking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Patient = cls.env['l10n_ua.medecin.patient']
        cls.Decl = cls.env['l10n_ua.medecin.declaration']
        cls.partner = cls.env['res.partner'].create({'name': 'Коваль Ольга'})
        cls.doctor = cls.env['hr.employee'].create({'name': 'Лікар Андрій'})
        cls.doctor2 = cls.env['hr.employee'].create({'name': 'Лікар Ірина'})

    def _messages(self, patient):
        # Tracking storage details differ between versions (mail_tracking is
        # a separate module in Odoo 20), so count the chatter messages.
        self.env.flush_all()
        self.env.cr.precommit.run()  # tracking messages are posted at precommit
        return self.env['mail.message'].sudo().search([
            ('model', '=', patient._name), ('res_id', '=', patient.id),
        ])

    def test_field_not_tracked(self):
        field = self.Patient._fields['active_doctor_id']
        self.assertFalse(getattr(field, 'tracking', None))
        self.assertNotIn('active_doctor_id', self.Patient._track_get_fields())
        # The source field on the declaration is still tracked.
        self.assertTrue(self.Decl._fields['doctor_id'].tracking)

    def test_no_note_on_declaration_change(self):
        patient = self.Patient.create({'partner_id': self.partner.id})
        before = self._messages(patient)
        d1 = self.Decl.create({'patient_id': patient.id, 'doctor_id': self.doctor.id})
        d1.action_activate()
        self.assertEqual(patient.active_doctor_id, self.doctor)
        d2 = self.Decl.create({'patient_id': patient.id, 'doctor_id': self.doctor2.id})
        d2.action_activate()
        self.assertEqual(patient.active_doctor_id, self.doctor2)
        self.assertEqual(self._messages(patient), before,
                         'declaration changes must not post notes on the patient')

    def test_no_note_with_tracking_disable(self):
        Patient = self.Patient.with_context(tracking_disable=True)
        Decl = self.Decl.with_context(tracking_disable=True)
        patients = Patient.create([
            {'partner_id': self.partner.id, 'patient_card_no': f'TRK-{i}'}
            for i in range(3)
        ])
        decls = Decl.create([
            {'patient_id': p.id, 'doctor_id': self.doctor.id} for p in patients
        ])
        decls.action_activate()
        for patient in patients:
            self.assertEqual(patient.active_doctor_id, self.doctor)
            self.assertFalse(self._messages(patient))
