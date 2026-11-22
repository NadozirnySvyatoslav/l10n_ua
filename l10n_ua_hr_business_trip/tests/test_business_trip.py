"""Звіт про відрядження (#207)."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestBusinessTrip(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.l10n_ua_business_trip_daily_rate = 300.0
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Відряджений Петро', 'company_id': cls.company.id})

    def _report(self, **kw):
        vals = {
            'employee_id': self.employee.id,
            'destination': 'Львів',
            'date_from': date(2025, 6, 2),
            'date_to': date(2025, 6, 5),
            'company_id': self.company.id,
        }
        vals.update(kw)
        return self.env['l10n_ua.business.trip.report'].create(vals)

    def test_days_and_daily_default(self):
        rec = self._report()
        # 2..5 червня включно = 4 дні
        self.assertEqual(rec.days, 4)
        # Норма добових успадкована з компанії
        self.assertAlmostEqual(rec.daily_rate, 300.0, places=2)

    def test_amounts(self):
        rec = self._report(
            transport_amount=500.0, accommodation_amount=1200.0,
            other_amount=100.0)
        # Добові 4 × 300 = 1200
        self.assertAlmostEqual(rec.daily_total, 1200.0, places=2)
        # Усього 1200 + 500 + 1200 + 100 = 3000
        self.assertAlmostEqual(rec.total_amount, 3000.0, places=2)

    def test_sequence_number(self):
        rec = self._report()
        self.assertNotEqual(rec.name, '/')
        self.assertTrue(rec.name.startswith('ЗВ-'))

    def test_sequence_number_in_second_company(self):
        """The report sequence is shared: another company gets a number too."""
        company_b = self.env['res.company'].create({'name': 'Друга компанія відряджень'})
        self.assertFalse(
            self.env.ref('l10n_ua_hr_business_trip.seq_business_trip_report').company_id)
        employee = self.env['hr.employee'].create({
            'name': 'Відряджений Друга', 'company_id': company_b.id})
        rec = self.env['l10n_ua.business.trip.report'].with_company(company_b).create({
            'employee_id': employee.id,
            'destination': 'Київ',
            'date_from': date(2025, 6, 2),
            'date_to': date(2025, 6, 3),
            'company_id': company_b.id,
        })
        self.assertTrue(rec.name.startswith('ЗВ-'))

    def test_invalid_dates(self):
        with self.assertRaises(UserError):
            self._report(date_from=date(2025, 6, 5), date_to=date(2025, 6, 2))

    def test_order_link_sets_employee(self):
        order = self.env['hr.order'].create({
            'order_type': 'business_trip',
            'employee_id': self.employee.id,
        })
        rec = self._report()
        rec.order_id = order
        rec._onchange_order_id()
        self.assertEqual(rec.employee_id, self.employee)

    def test_create_advance_report(self):
        rec = self._report(transport_amount=500.0, accommodation_amount=1200.0)
        rec.action_confirm()
        rec.action_create_advance_report()
        adv = rec.advance_report_id
        self.assertTrue(adv)
        self.assertEqual(adv.employee_id, self.employee)
        # Рядки: добові + проїзд + проживання = 3 (other = 0, пропущено)
        self.assertEqual(len(adv.line_ids), 3)
        # Загальна сума збігається
        self.assertAlmostEqual(adv.total_expenses, rec.total_amount, places=2)
        types = set(adv.line_ids.mapped('expense_type'))
        self.assertEqual(types, {'meals', 'transport', 'accommodation'})

    def test_create_advance_report_twice_blocked(self):
        rec = self._report(transport_amount=500.0)
        rec.action_confirm()
        rec.action_create_advance_report()
        with self.assertRaises(UserError):
            rec.action_create_advance_report()

    def test_create_advance_report_no_expenses(self):
        rec = self._report()
        rec.daily_rate = 0.0
        rec.action_confirm()
        with self.assertRaises(UserError):
            rec.action_create_advance_report()
