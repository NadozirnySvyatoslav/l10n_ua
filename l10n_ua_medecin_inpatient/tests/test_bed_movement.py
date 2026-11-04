"""Ліжковий фонд, переведення, ф. 007/о і показники стаціонару (#227)."""
from datetime import date, datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


BALANCE_IN = ('count_start', 'admitted', 'transferred_in')
BALANCE_OUT = ('discharged', 'died', 'transferred_out')


@tagged('post_install', '-at_install', 'l10n_ua_medecin_inpatient')
class TestBedMovement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Київ у березні 2026 — UTC+2 (перехід на літній час 29.03).
        cls.company.partner_id.tz = 'Europe/Kyiv'
        Dept = cls.env['l10n_ua.medecin.department']
        cls.ter = Dept.create({'name': 'Терапія', 'code': 'T227', 'company_id': cls.company.id})
        cls.sur = Dept.create({'name': 'Хірургія', 'code': 'S227', 'company_id': cls.company.id})
        Bed = cls.env['l10n_ua.medecin.bed']
        cls.ter_beds = Bed.create([
            {'department_id': cls.ter.id, 'ward': '1', 'name': str(n)} for n in range(1, 5)])
        cls.sur_beds = Bed.create([
            {'department_id': cls.sur.id, 'ward': '7', 'name': str(n)} for n in range(1, 3)])
        cls.patients = cls.env['l10n_ua.medecin.patient'].create([{
            'partner_id': cls.env['res.partner'].create({'name': f'Пацієнт {n}'}).id,
            'company_id': cls.company.id,
        } for n in range(10)])
        cls.Admission = cls.env['l10n_ua.medecin.admission']
        # Якщо встановлено типи діагнозів (#225), виписка вимагає заключного
        # діагнозу — додаємо його, щоб тести руху не залежали від порядку злиття.
        Diagnosis = cls.env['l10n_ua.medecin.diagnosis']
        cls.final_diagnosis = (
            'diagnosis_ids' in cls.Admission._fields
            and 'diagnosis_type' in Diagnosis._fields
            and 'admission_id' in Diagnosis._fields)
        cls.icd10 = cls.env['l10n_ua.medecin.icd10'].search(
            [('is_selectable', '=', True)], limit=1)

    def _adm(self, n, date_in, dept=None, date_out=None, died=False, state='admitted', **kw):
        adm = self.Admission.create(dict({
            'patient_id': self.patients[n].id,
            'company_id': self.company.id,
            'department_id': (dept or self.ter).id,
            'date_admission': date_in,
        }, **kw))
        if self.final_diagnosis:
            adm.diagnosis_ids = [Command.create({
                'icd10_id': self.icd10.id, 'diagnosis_type': 'final'})]
        if state in ('admitted', 'discharged'):
            adm.action_admit()
        return adm

    def _discharge(self, adm, date_out, died=False):
        adm.write({
            'date_discharge': date_out,
            'treatment_result': 'death' if died else 'improvement',
            'discharge_type': 'died' if died else 'home',
        })
        adm.action_discharge()

    def _transfer(self, adm, when, dept, bed=None):
        return self.env['l10n_ua.medecin.admission.transfer'].create({
            'admission_id': adm.id,
            'date': when,
            'department_to_id': dept.id,
            'bed_id': bed.id if bed else False,
        })

    def _scenario(self):
        """Рух навколо доби 10.03.2026 (місцевий час = UTC + 2)."""
        a1 = self._adm(0, datetime(2026, 3, 8, 8, 0))                 # лежить
        a2 = self._adm(1, datetime(2026, 3, 9, 8, 0))
        self._discharge(a2, datetime(2026, 3, 10, 9, 0))               # виписаний 10.03
        a3 = self._adm(2, datetime(2026, 3, 10, 7, 0))                 # поступив 10.03
        a4 = self._adm(3, datetime(2026, 3, 8, 9, 0))
        self._transfer(a4, datetime(2026, 3, 10, 10, 0), self.sur)     # T → S 10.03
        a5 = self._adm(4, datetime(2026, 3, 10, 6, 0))
        self._discharge(a5, datetime(2026, 3, 10, 15, 0), died=True)   # поступив і помер 10.03
        # 23:00 UTC 09.03 = 01:00 10.03 за Києвом → поступлення 10.03.
        a6 = self._adm(5, datetime(2026, 3, 9, 23, 0))
        self._adm(6, datetime(2026, 3, 10, 8, 0), state='draft')       # не враховується
        cancelled = self._adm(7, datetime(2026, 3, 10, 8, 0))
        cancelled.action_cancel()                                       # не враховується
        self._adm(8, datetime(2026, 3, 11, 8, 0))                      # після доби
        return a1, a2, a3, a4, a5, a6

    def _assert_balanced(self, res, label=''):
        expected = sum(res[k] for k in BALANCE_IN) - sum(res[k] for k in BALANCE_OUT)
        self.assertEqual(res['count_end'], expected, f'Баланс руху не сходиться {label}: {res}')

    # --- Рух за добу (ф. 007/о) ---

    def test_daily_movement_balance(self):
        self._scenario()
        day = date(2026, 3, 10)
        data = (self.ter | self.sur)._get_bed_movement(day, day)
        ter, sur = data[self.ter.id], data[self.sur.id]
        self.assertEqual(
            {k: ter[k] for k in ('count_start', 'admitted', 'transferred_in', 'discharged',
                                 'died', 'transferred_out', 'count_end')},
            {'count_start': 3, 'admitted': 3, 'transferred_in': 0, 'discharged': 1,
             'died': 1, 'transferred_out': 1, 'count_end': 3})
        self.assertEqual(
            {k: sur[k] for k in ('count_start', 'admitted', 'transferred_in', 'count_end')},
            {'count_start': 0, 'admitted': 0, 'transferred_in': 1, 'count_end': 1})
        self._assert_balanced(ter, 'Терапія')
        self._assert_balanced(sur, 'Хірургія')
        # Ліжко-дні доби: пацієнти на кінець доби + 1 за поступив-і-вибув того ж дня.
        self.assertEqual(ter['bed_days'], 4)
        self.assertEqual(sur['bed_days'], 1)
        self.assertEqual(ter['bed_count'], 4)

    def test_movement_balance_over_days(self):
        self._scenario()
        depts = self.ter | self.sur
        prev = None
        for offset in range(-3, 4):
            day = date(2026, 3, 10) + timedelta(days=offset)
            data = depts._get_bed_movement(day, day)
            for dept in depts:
                self._assert_balanced(data[dept.id], f'{dept.code} {day}')
                if prev:
                    # Залишок на кінець доби = залишок на початок наступної.
                    self.assertEqual(prev[dept.id]['count_end'], data[dept.id]['count_start'])
            prev = data
        # Період з кількох діб також сходиться.
        data = depts._get_bed_movement(date(2026, 3, 7), date(2026, 3, 13))
        for dept in depts:
            self._assert_balanced(data[dept.id], f'{dept.code} період')

    def test_period_bed_days_match_admissions(self):
        a1, a2, a3, a4, a5, a6 = self._scenario()
        for adm, out in ((a1, datetime(2026, 3, 14, 8, 0)), (a3, datetime(2026, 3, 12, 8, 0)),
                         (a4, datetime(2026, 3, 13, 8, 0)), (a6, datetime(2026, 3, 10, 20, 0))):
            self._discharge(adm, out)
        self.Admission.search([('patient_id', '=', self.patients[8].id)]).action_cancel()
        data = (self.ter | self.sur)._get_bed_movement(date(2026, 3, 1), date(2026, 3, 31))
        total = sum(d['bed_days'] for d in data.values())
        self.assertEqual(total, sum((a1 | a2 | a3 | a4 | a5 | a6).mapped('bed_days')))
        # a4: 08.03 → 10.03 у терапії (2 ночі), 10.03 → 13.03 у хірургії (3 ночі).
        self.assertEqual(data[self.sur.id]['bed_days'], 3)

    # --- Показники за період ---

    def test_period_indicators(self):
        x1 = self._adm(0, datetime(2026, 1, 5, 8, 0))
        self._discharge(x1, datetime(2026, 1, 15, 8, 0))              # 10 ліжко-днів
        x2 = self._adm(1, datetime(2026, 1, 10, 8, 0))
        self._discharge(x2, datetime(2026, 1, 12, 8, 0), died=True)   # 2 ліжко-дні
        # Одне з 4 ліжок терапії згорнуте з 16.01 (15 днів у фонді за січень).
        self.ter_beds[3].date_close = date(2026, 1, 16)
        wizard = self.env['l10n_ua.medecin.bed.indicators'].create({
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 31),
            'department_ids': [(6, 0, self.ter.ids)],
        })
        wizard.action_compute()
        line = wizard.line_ids.filtered(lambda l: l.department_id == self.ter)
        avg_beds = 3 + 15 / 31
        self.assertAlmostEqual(line.avg_beds, avg_beds, places=2)
        self.assertEqual(line.bed_days, 12)
        self.assertEqual(line.departed, 2)
        self.assertAlmostEqual(line.occupancy_days, 12 / avg_beds, places=1)
        self.assertAlmostEqual(line.occupancy_days_year, 12 / avg_beds * 365 / 31, places=1)
        self.assertAlmostEqual(line.bed_turnover, 2 / avg_beds, places=2)
        self.assertAlmostEqual(line.avg_stay, 6.0, places=1)
        self.assertAlmostEqual(line.mortality, 50.0, places=2)
        total = wizard.line_ids.filtered('is_total')
        self.assertEqual(total.bed_days, 12)

    def test_hospital_total_excludes_internal_transfers(self):
        adm = self._adm(0, datetime(2026, 2, 1, 8, 0))
        self._transfer(adm, datetime(2026, 2, 3, 8, 0), self.sur)
        self._discharge(adm, datetime(2026, 2, 5, 8, 0))
        wizard = self.env['l10n_ua.medecin.bed.indicators'].create({
            'date_from': date(2026, 2, 1), 'date_to': date(2026, 2, 28),
            'department_ids': [(6, 0, (self.ter | self.sur).ids)],
        })
        wizard.action_compute()
        by_dept = {l.department_id: l for l in wizard.line_ids if not l.is_total}
        total = wizard.line_ids.filtered('is_total')
        self.assertEqual(by_dept[self.ter].departed, 1)   # переведено в хірургію
        self.assertEqual(by_dept[self.sur].departed, 1)   # виписано
        self.assertEqual(total.departed, 1)
        self.assertEqual(total.bed_days, 4)
        self.assertAlmostEqual(total.avg_stay, 4.0)
        self.assertEqual(total.mortality, 0.0)

    def test_007o_wizard_and_print(self):
        self._scenario()
        wizard = self.env['l10n_ua.medecin.report.007o'].create({'date': date(2026, 3, 10)})
        wizard.action_compute()
        lines = wizard.line_ids.filtered(lambda l: l.department_id in (self.ter | self.sur))
        self.assertEqual(len(lines), 2)
        ter = lines.filtered(lambda l: l.department_id == self.ter)
        self.assertEqual(ter.count_end, 3)
        self.assertEqual(ter.bed_free, 1)
        total = wizard.line_ids.filtered('is_total')
        self.assertEqual(len(total), 1)
        for line in wizard.line_ids:
            self.assertEqual(
                line.count_end,
                line.count_start + line.admitted + line.transferred_in
                - line.discharged - line.died - line.transferred_out,
                line.display_name)
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_medecin_inpatient.action_report_007o', wizard.ids)
        self.assertIn('007/о', html.decode())
        self.assertIn('Терапія', html.decode())

    # --- Ліжка ---

    def test_bed_fund_and_occupancy(self):
        bed = self.ter_beds[0]
        self.assertEqual(self.ter.bed_count, 4)
        adm = self._adm(0, datetime(2026, 3, 1, 8, 0), bed_id=bed.id)
        self.env.invalidate_all()
        self.assertTrue(bed.is_occupied)
        self.assertEqual(bed.admission_id, adm)
        self.assertEqual(self.ter.bed_occupied_count, 1)
        self.assertEqual(self.ter.bed_free_count, 3)
        self.assertIn(bed, self.env['l10n_ua.medecin.bed'].search([('is_occupied', '=', True)]))
        with self.assertRaises(ValidationError):
            self._adm(1, datetime(2026, 3, 2, 8, 0), bed_id=bed.id)
        with self.assertRaises(ValidationError):
            self._adm(2, datetime(2026, 3, 2, 8, 0), bed_id=self.sur_beds[0].id)
        self._discharge(adm, datetime(2026, 3, 4, 8, 0))
        self.env.invalidate_all()
        self.assertFalse(bed.is_occupied)
        # Згорнуте ліжко виходить із фонду; архівоване — з обліку.
        self.ter_beds[1].date_close = date(2020, 1, 1)
        self.ter_beds[1].date_open = date(2019, 1, 1)
        self.ter_beds[2].active = False
        self.env.invalidate_all()
        self.assertEqual(self.ter.bed_count, 2)
        with self.assertRaises(ValidationError):
            self.ter_beds[0].write({'date_open': date(2026, 2, 1), 'date_close': date(2026, 1, 1)})

    # --- Переведення ---

    def test_transfer_moves_department_and_bed(self):
        adm = self._adm(0, datetime(2026, 3, 1, 8, 0), bed_id=self.ter_beds[0].id)
        self._transfer(adm, datetime(2026, 3, 2, 8, 0), self.sur, self.sur_beds[0])
        self.assertEqual(adm.department_id, self.sur)
        self.assertEqual(adm.bed_id, self.sur_beds[0])
        stays = adm._get_department_stays()
        self.assertEqual([s[0] for s in stays], [self.ter, self.sur])
        # Не можна перевести в те саме відділення, раніше госпіталізації чи
        # раніше попереднього переведення.
        with self.assertRaises(ValidationError):
            self._transfer(adm, datetime(2026, 3, 3, 8, 0), self.sur)
        with self.assertRaises(ValidationError):
            self._transfer(adm, datetime(2026, 2, 1, 8, 0), self.ter)
        with self.assertRaises(ValidationError):
            self._transfer(adm, datetime(2026, 3, 1, 12, 0), self.ter)
        # Ручна зміна відділення в обхід переведення заборонена.
        with self.assertRaises(ValidationError):
            adm.department_id = self.ter
        # Видалення останнього переведення повертає відділення.
        adm.transfer_ids.unlink()
        self.assertEqual(adm.department_id, self.ter)
        self.assertFalse(adm.bed_id)

    def test_transfer_requires_admitted(self):
        adm = self._adm(0, datetime(2026, 3, 1, 8, 0), state='draft')
        with self.assertRaises(UserError):
            self._transfer(adm, datetime(2026, 3, 2, 8, 0), self.sur)
        adm.action_admit()
        transfer = self._transfer(adm, datetime(2026, 3, 2, 8, 0), self.sur)
        with self.assertRaises(UserError):
            transfer.department_to_id = self.ter
        with self.assertRaises(ValidationError):
            # Виписка раніше переведення.
            self._discharge(adm, datetime(2026, 3, 1, 20, 0))

    # --- Інтерфейс ---

    def test_bed_actions_views_load(self):
        for xmlid in (
            'l10n_ua_medecin_inpatient.action_bed',
            'l10n_ua_medecin_inpatient.action_report_007o_wizard',
            'l10n_ua_medecin_inpatient.action_bed_indicators_wizard',
        ):
            action = self.env.ref(xmlid)
            modes = action.view_mode.split(',')
            res = self.env[action.res_model].get_views([(False, m) for m in modes])
            for mode in modes:
                self.assertIn(mode, res['views'], f'{xmlid}: {mode}')
        res = self.Admission.get_views([(False, 'form')])
        self.assertIn('action_transfer', res['views']['form']['arch'])
        res = self.env['l10n_ua.medecin.admission.transfer'].get_views([(False, 'form')])
        self.assertIn('department_to_id', res['views']['form']['arch'])
