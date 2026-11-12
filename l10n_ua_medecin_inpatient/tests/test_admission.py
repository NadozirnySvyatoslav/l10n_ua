"""Епізод стаціонарного лікування: життєвий цикл, ліжко-дні, мультикомпанійність (#224)."""
from datetime import datetime

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo import Command
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install', 'l10n_ua_medecin_inpatient')
class TestMedecinAdmission(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Детерміновані ліжко-дні: часовий пояс закладу — Київ.
        cls.company.partner_id.tz = 'Europe/Kyiv'
        cls.partner = cls.env['res.partner'].create({'name': 'Коваленко Петро'})
        cls.patient = cls.env['l10n_ua.medecin.patient'].create({
            'partner_id': cls.partner.id,
            'company_id': cls.company.id,
        })
        cls.doctor = cls.env['hr.employee'].create({
            'name': 'Лікар Ольга', 'company_id': cls.company.id})
        cls.department = cls.env['l10n_ua.medecin.department'].create({
            'name': 'Терапевтичне відділення', 'code': 'TER',
            'company_id': cls.company.id,
        })
        cls.Admission = cls.env['l10n_ua.medecin.admission']
        cls.icd10 = cls.env['l10n_ua.medecin.icd10'].search(
            [('is_selectable', '=', True)], limit=1)

    def _admission(self, **vals):
        base = {
            'patient_id': self.patient.id,
            'doctor_id': self.doctor.id,
            'department_id': self.department.id,
            'company_id': self.company.id,
            'date_admission': datetime(2026, 3, 10, 8, 0),
            # Виписка вимагає заключного діагнозу (#225).
            'diagnosis_ids': [Command.create({
                'icd10_id': self.icd10.id, 'diagnosis_type': 'final'})],
        }
        base.update(vals)
        return self.Admission.create(base)

    # --- Нумерація ф. 003/о ---

    def test_card_number_autoassigned(self):
        a1 = self._admission()
        a2 = self._admission()
        self.assertTrue(a1.name.startswith('СТ-'), a1.name)
        self.assertNotEqual(a1.name, 'Нова')
        self.assertNotEqual(a1.name, a2.name)
        self.assertIn(a1.name, a1.display_name)
        self.assertIn(self.patient.display_name, a1.display_name)

    # --- Життєвий цикл ---

    def test_lifecycle_full(self):
        adm = self._admission()
        self.assertEqual(adm.state, 'draft')
        adm.action_admit()
        self.assertEqual(adm.state, 'admitted')
        adm.write({
            'date_discharge': datetime(2026, 3, 15, 10, 0),
            'treatment_result': 'improvement',
            'discharge_type': 'home',
        })
        adm.action_discharge()
        self.assertEqual(adm.state, 'discharged')
        self.assertEqual(adm.bed_days, 5)
        # Повернення на лікування і скасування.
        adm.action_reopen()
        self.assertEqual(adm.state, 'admitted')
        adm.action_cancel()
        self.assertEqual(adm.state, 'cancelled')
        adm.action_draft()
        self.assertEqual(adm.state, 'draft')

    def test_discharge_sets_date_when_empty(self):
        adm = self._admission(date_admission=datetime(2020, 1, 1, 8, 0))
        adm.action_admit()
        adm.write({'treatment_result': 'recovery', 'discharge_type': 'home'})
        adm.action_discharge()
        self.assertTrue(adm.date_discharge)
        self.assertGreater(adm.bed_days, 0)

    def test_cannot_discharge_not_admitted(self):
        adm = self._admission(
            treatment_result='recovery', discharge_type='home',
            date_discharge=datetime(2026, 3, 12, 8, 0))
        with self.assertRaises(UserError):
            adm.action_discharge()  # ще чернетка
        adm.action_cancel()
        with self.assertRaises(UserError):
            adm.action_discharge()  # скасований
        self.assertEqual(adm.state, 'cancelled')

    def test_discharge_requires_result(self):
        adm = self._admission()
        adm.action_admit()
        with self.assertRaises(ValidationError):
            adm.action_discharge()

    def test_death_result_consistency(self):
        adm = self._admission()
        adm.action_admit()
        with self.assertRaises(ValidationError):
            adm.write({'treatment_result': 'death', 'discharge_type': 'home'})
        with self.assertRaises(ValidationError):
            adm.write({'treatment_result': 'improvement', 'discharge_type': 'died'})
        adm.write({'treatment_result': 'death', 'discharge_type': 'died',
                   'date_discharge': datetime(2026, 3, 11, 3, 0)})
        adm.action_discharge()
        self.assertEqual(adm.state, 'discharged')

    def test_cannot_admit_twice_or_cancel_discharged(self):
        adm = self._admission()
        adm.action_admit()
        with self.assertRaises(UserError):
            adm.action_admit()
        adm.write({'treatment_result': 'recovery', 'discharge_type': 'home',
                   'date_discharge': datetime(2026, 3, 12, 8, 0)})
        adm.action_discharge()
        with self.assertRaises(UserError):
            adm.action_cancel()
        with self.assertRaises(UserError):
            adm.unlink()

    def test_discharge_before_admission_rejected(self):
        with self.assertRaises(ValidationError):
            self._admission(date_discharge=datetime(2026, 3, 9, 8, 0))

    # --- Ліжко-дні ---

    def test_bed_days_rules(self):
        cases = [
            # (поступлення UTC, виписка UTC, очікувані ліжко-дні)
            (datetime(2026, 3, 10, 8, 0), datetime(2026, 3, 10, 15, 0), 1),   # той самий день
            (datetime(2026, 3, 10, 8, 0), datetime(2026, 3, 10, 8, 0), 1),    # та сама мить
            (datetime(2026, 3, 10, 18, 0), datetime(2026, 3, 11, 6, 0), 1),   # одна ніч
            (datetime(2026, 3, 10, 8, 0), datetime(2026, 3, 20, 8, 0), 10),
            # 23:30 UTC 10.03 = 01:30 11.03 за Києвом → обидві дати 11.03
            (datetime(2026, 3, 10, 23, 30), datetime(2026, 3, 11, 12, 0), 1),
            # 21:30 UTC 09.03 = 23:30 09.03 за Києвом → 09.03 → 11.03 = 2
            (datetime(2026, 3, 9, 21, 30), datetime(2026, 3, 11, 12, 0), 2),
        ]
        for date_in, date_out, expected in cases:
            adm = self._admission(date_admission=date_in, date_discharge=date_out)
            self.assertEqual(adm.bed_days, expected, f'{date_in} → {date_out}')

    def test_bed_days_zero_until_discharge(self):
        adm = self._admission()
        adm.action_admit()
        self.assertEqual(adm.bed_days, 0)
        adm.date_discharge = datetime(2026, 3, 13, 9, 0)
        self.assertEqual(adm.bed_days, 3)

    # --- Мультикомпанійність ---

    def test_rules_exist_and_global(self):
        for xmlid in (
            'l10n_ua_medecin_inpatient.l10n_ua_medecin_admission_company_rule',
            'l10n_ua_medecin_inpatient.l10n_ua_medecin_department_company_rule',
        ):
            self.assertTrue(self.env.ref(xmlid)['global'], xmlid)

    def test_multicompany_isolation(self):
        company_b = self.env['res.company'].create({'name': 'Лікарня Б'})
        adm_a = self._admission()
        partner_b = self.env['res.partner'].create({'name': 'Пацієнт Б'})
        patient_b = self.env['l10n_ua.medecin.patient'].create({
            'partner_id': partner_b.id, 'company_id': company_b.id})
        adm_b = self.Admission.create({
            'patient_id': patient_b.id,
            'company_id': company_b.id,
            'date_admission': datetime(2026, 3, 10, 8, 0),
        })
        user_b = new_test_user(
            self.env, login='medecin_inpatient_b',
            groups='l10n_ua_medecin_base.group_ua_medecin_user',
            company_id=company_b.id, company_ids=[(6, 0, company_b.ids)])
        Adm_b = self.Admission.with_user(user_b)
        visible = Adm_b.search([('id', 'in', (adm_a | adm_b).ids)])
        self.assertEqual(visible, adm_b)
        with self.assertRaises(AccessError):
            adm_a.with_user(user_b).read(['name'])

    def test_cross_company_patient_rejected(self):
        company_b = self.env['res.company'].create({'name': 'Лікарня В'})
        with self.assertRaises(UserError):
            self._admission(company_id=company_b.id)

    def test_no_access_without_medecin_group(self):
        user = new_test_user(self.env, login='plain_inpatient_user',
                             groups='base.group_user')
        with self.assertRaises(AccessError):
            self.Admission.with_user(user).search([])

    # --- Інтерфейс ---

    def test_actions_views_load(self):
        for xmlid in (
            'l10n_ua_medecin_inpatient.action_admission',
            'l10n_ua_medecin_inpatient.action_admission_current',
            'l10n_ua_medecin_inpatient.action_report_admission',
            'l10n_ua_medecin_inpatient.action_department',
        ):
            action = self.env.ref(xmlid)
            modes = action.view_mode.split(',')
            res = self.env[action.res_model].get_views(
                [(False, m) for m in modes] + [(action.search_view_id.id, 'search')])
            for mode in modes:
                self.assertIn(mode, res['views'], f'{xmlid}: {mode}')
