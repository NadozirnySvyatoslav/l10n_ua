"""Tests for hr.employee.transfer.wizard — issue #32."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestEmployeeTransfer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Transfer Target Co'})
        cls.env.user.write({'company_ids': [(4, cls.company_b.id)]})

        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Target Dept', 'company_id': cls.company_b.id,
        })
        cls.job_b = cls.env['hr.job'].create({
            'name': 'Target Job', 'company_id': cls.company_b.id,
        })

        cls.source_employee = cls.env['hr.employee'].with_company(cls.company_a).create({
            'name': 'Іван Петренко',
            'company_id': cls.company_a.id,
            'rnokpp': '1234567899',
            'birthday': date(1990, 3, 15),
            'passport_id': '123456789',
            'document_type': 'id_card',
            'work_phone': '+380501112233',
            'mobile_phone': '+380671112233',
            'work_email': 'ivan@example.com',
            'private_phone': '+380931112233',
            'private_email': 'ivan.private@example.com',
            'job_title': 'Інженер',
            'hire_date': date(2020, 1, 10),
        })

    def _make_wizard(self, **overrides):
        vals = {
            'source_employee_id': self.source_employee.id,
            'source_company_id': self.company_a.id,
            'target_company_id': self.company_b.id,
            'dismissal_date': date(2026, 4, 30),
            'hire_date': date(2026, 5, 1),
            'new_department_id': self.dept_b.id,
            'new_job_id': self.job_b.id,
        }
        vals.update(overrides)
        return self.env['hr.employee.transfer.wizard'].create(vals)

    def test_transfer_creates_new_employee(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        self.assertTrue(new_employee)
        self.assertEqual(new_employee.company_id, self.company_b)
        self.assertEqual(new_employee.name, 'Іван Петренко')
        self.assertEqual(new_employee.rnokpp, '1234567899')
        self.assertEqual(new_employee.previous_employee_id, self.source_employee)

    def test_transfer_deactivates_source(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        self.source_employee.invalidate_recordset(['active'])
        self.assertFalse(self.source_employee.active)

    def test_transfer_creates_hr_orders(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id

        dismissal_orders = self.env['hr.order'].search([
            ('employee_id', '=', self.source_employee.id),
            ('order_type', '=', 'dismissal'),
        ])
        self.assertTrue(dismissal_orders, 'Dismissal hr.order must be created')
        self.assertEqual(dismissal_orders.date_dismissal, date(2026, 4, 30))

        hiring_orders = self.env['hr.order'].search([
            ('employee_id', '=', new_employee.id),
            ('order_type', '=', 'hiring'),
        ])
        self.assertTrue(hiring_orders, 'Hiring hr.order must be created')
        self.assertEqual(hiring_orders.date_start, date(2026, 5, 1))

    def test_transfer_copies_address_fields(self):
        """Test that transfer wizard copies private address and registration address fields."""
        self.source_employee.write({
            'private_street': 'Хрещатик 1',
            'private_street2': 'кв. 10',
            'private_city': 'Київ',
            'private_zip': '01001',
            'registration_street': 'Шевченка 10',
            'registration_street2': 'кв. 5',
            'registration_city': 'Львів',
            'registration_zip': '79000',
            'registration_same_as_actual': False,
        })
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id

        self.assertEqual(new_employee.private_street, 'Хрещатик 1')
        self.assertEqual(new_employee.private_street2, 'кв. 10')
        self.assertEqual(new_employee.registration_street, 'Шевченка 10')
        self.assertEqual(new_employee.registration_street2, 'кв. 5')
        self.assertEqual(new_employee.registration_city, 'Львів')
        self.assertFalse(new_employee.registration_same_as_actual)

    def test_transfer_keeps_mirrored_registration_address(self):
        """Із прапорцем збігу перенесена реєстрація дзеркалить приватну адресу."""
        self.source_employee.write({
            'private_street': 'Хрещатик 1',
            'private_street2': 'кв. 10',
            'private_city': 'Київ',
            'registration_same_as_actual': True,
        })
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id

        self.assertTrue(new_employee.registration_same_as_actual)
        self.assertEqual(new_employee.registration_street, 'Хрещатик 1')
        self.assertEqual(new_employee.registration_street2, 'кв. 10')
        self.assertEqual(new_employee.registration_city, 'Київ')

    def test_cannot_transfer_to_same_company(self):
        with self.assertRaises(UserError):
            self._make_wizard(target_company_id=self.company_a.id)

    def test_cannot_transfer_twice(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        with self.assertRaises(UserError):
            wizard.action_transfer()

    def test_hire_date_autocomputed(self):
        wizard = self.env['hr.employee.transfer.wizard'].create({
            'source_employee_id': self.source_employee.id,
            'source_company_id': self.company_a.id,
            'target_company_id': self.company_b.id,
            'dismissal_date': date(2026, 4, 30),
        })
        self.assertEqual(wizard.hire_date, date(2026, 5, 1))

    def test_hire_before_dismissal_rejected(self):
        with self.assertRaises(UserError):
            self._make_wizard(hire_date=date(2026, 4, 29))

    def test_vacation_reset_is_default(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard.vacation_transfer_mode, 'reset')

    def test_transfer_copies_personal_and_contact_fields(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        # Hire date must reflect the wizard's target hire date, not the source's.
        self.assertEqual(new_employee.hire_date, date(2026, 5, 1))
        # Birthday and passport must be carried over (fields previously dropped).
        self.assertEqual(new_employee.birthday, date(1990, 3, 15))
        self.assertEqual(new_employee.passport_id, '123456789')
        self.assertEqual(new_employee.document_type, 'id_card')
        # Header contact info shown right under the name.
        self.assertEqual(new_employee.work_phone, '+380501112233')
        self.assertEqual(new_employee.mobile_phone, '+380671112233')
        self.assertEqual(new_employee.work_email, 'ivan@example.com')
        self.assertEqual(new_employee.private_phone, '+380931112233')
        self.assertEqual(new_employee.private_email, 'ivan.private@example.com')
        # The job title follows the NEW position instead of being carried over:
        # copying it would freeze "Інженер" on a card whose job_id — and every
        # printed order — says "Target Job".
        self.assertEqual(new_employee.job_id, self.job_b)
        self.assertEqual(new_employee.job_title, 'Target Job')

    def test_documents_not_copied_when_flag_off(self):
        wizard = self._make_wizard(copy_documents=False)
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        self.assertFalse(new_employee.passport_id)

    def test_transfer_links_salary_accounts(self):
        """Salary accounts follow the employee onto the target card.

        Only the accounts the source used for payroll are linked; a private
        account of the same contact is copied but left unlinked.
        """
        source_contact = self.source_employee.work_contact_id
        salary_account = self.env['res.partner.bank'].create({
            'acc_number': 'UA213223130000026007233566001',
            'partner_id': source_contact.id,
            'allow_out_payment': True,
        })
        private_account = self.env['res.partner.bank'].create({
            'acc_number': 'UA913223130000026007233566002',
            'partner_id': source_contact.id,
        })
        self.source_employee.bank_account_ids = [(4, salary_account.id)]

        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id

        linked = new_employee.bank_account_ids
        self.assertEqual(len(linked), 1)
        self.assertNotIn(linked.id, (salary_account.id, private_account.id))
        self.assertEqual(linked.acc_number, salary_account.acc_number)
        self.assertEqual(linked.partner_id, new_employee.work_contact_id)
        self.assertEqual(linked.company_id, self.company_b)
        # copy=False on allow_out_payment: the copy must arrive untrusted.
        self.assertFalse(linked.allow_out_payment)
        # Both accounts are still copied, only one of them is linked.
        self.assertEqual(len(new_employee.work_contact_id.bank_ids), 2)

    def test_bank_accounts_not_copied_when_flag_off(self):
        source_contact = self.source_employee.work_contact_id
        account = self.env['res.partner.bank'].create({
            'acc_number': 'UA213223130000026007233566001',
            'partner_id': source_contact.id,
        })
        self.source_employee.bank_account_ids = [(4, account.id)]
        wizard = self._make_wizard(copy_bank_accounts=False)
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        self.assertFalse(new_employee.bank_account_ids)

    # --- #154: авто-версія контракту + форма П-7 ---

    def _source_with_version(self):
        """Дати джерелу поточну версію контракту з окладом та умовами."""
        version = self.env['hr.version'].create({
            'employee_id': self.source_employee.id,
            'company_id': self.company_a.id,
            'contract_date_start': date(2020, 1, 10),
            'date_version': date(2020, 1, 10),
            'wage': 25000.0,
        })
        if 'contract_type_ua' in version._fields:
            version.contract_type_ua = 'permanent'
        if 'work_mode' in version._fields:
            version.work_mode = 'full_time'
        self.source_employee.current_version_id = version.id
        return version

    def test_transfer_creates_new_version(self):
        self._source_with_version()
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        version = new_employee.current_version_id
        self.assertTrue(version)
        self.assertEqual(version.employee_id, new_employee)
        self.assertEqual(version.company_id, self.company_b)
        self.assertEqual(version.contract_date_start, date(2026, 5, 1))
        # Оклад перенесено з джерела за згодою.
        self.assertAlmostEqual(version.wage, 25000.0, places=2)

    def test_hire_date_comes_from_the_new_version(self):
        """The wizard writes no employee-level hire date: it derives from the
        contract version created for the target company."""
        self._source_with_version()
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        version = new_employee.current_version_id
        self.assertEqual(version.contract_date_start, date(2026, 5, 1))
        self.assertEqual(new_employee.hire_date, version.contract_date_start)
        # The source keeps its own anchor - the transfer must not move it.
        self.assertEqual(self.source_employee.hire_date, date(2020, 1, 10))

    def test_hiring_order_marked_p7_and_linked(self):
        self._source_with_version()
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        hiring = self.env['hr.order'].search([
            ('employee_id', '=', new_employee.id),
            ('order_type', '=', 'hiring'),
        ], limit=1)
        self.assertEqual(hiring.personnel_form, 'p7')
        self.assertEqual(hiring.new_version_id, new_employee.current_version_id)

    def test_dismissal_order_marked_p4(self):
        wizard = self._make_wizard()
        wizard.action_transfer()
        dismissal = self.env['hr.order'].search([
            ('employee_id', '=', self.source_employee.id),
            ('order_type', '=', 'dismissal'),
        ], limit=1)
        self.assertEqual(dismissal.personnel_form, 'p4')

    def test_wage_not_copied_when_flag_off(self):
        self._source_with_version()
        wizard = self._make_wizard(copy_wage=False, new_wage=18000.0)
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        self.assertAlmostEqual(new_employee.current_version_id.wage, 18000.0, places=2)

    def test_no_duplicate_version(self):
        self._source_with_version()
        wizard = self._make_wizard()
        wizard.action_transfer()
        new_employee = self.source_employee.next_employee_id
        versions = self.env['hr.version'].with_context(active_test=False).search([
            ('employee_id', '=', new_employee.id),
        ])
        # Наказ прийняття доповнює створену версію, а не дублює її.
        self.assertEqual(len(versions), 1)

    # ------------------------------------------------------------------
    # Vacation balance transfer (period-based)
    # ------------------------------------------------------------------

    def _skip_if_no_balance(self):
        if 'hr.vacation.balance' not in self.env:
            self.skipTest('l10n_ua_hr_holidays not installed')

    def _new_balance_of(self, leave_type):
        return self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.source_employee.next_employee_id.id),
            ('leave_type_id', '=', leave_type.id),
        ])

    def test_transfer_keep_work_year(self):
        """keep: the transferred work-year balance keeps the source period
        bounds, and the seniority anchor travels to the new employee."""
        self._skip_if_no_balance()
        annual = self.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        # Source work-year period that contains the transfer date (2026-05-01).
        self.env['hr.vacation.balance'].create({
            'employee_id': self.source_employee.id,
            'leave_type_id': annual.id,
            'period_start': date(2026, 1, 10),
            'period_end': date(2027, 1, 9),
            'period_index': 7,
            'entitled_days': 24,
        })
        wizard = self._make_wizard(vacation_transfer_mode='transfer',
                                   vacation_period_mode='keep')
        wizard.action_transfer()

        new_bal = self._new_balance_of(annual)
        self.assertTrue(new_bal)
        self.assertEqual(new_bal.period_start, date(2026, 1, 10))
        self.assertEqual(new_bal.period_end, date(2027, 1, 9))
        self.assertEqual(new_bal.carried_over, 24)
        new_employee = self.source_employee.next_employee_id
        # The new contract still starts on the transfer date — only the
        # vacation seniority continues, through the anchor.
        self.assertEqual(new_employee.hire_date, date(2026, 5, 1))
        self.assertEqual(new_employee.vacation_anchor_date,
                         self.source_employee.hire_date)
        # ...so the next work year lines up with the carried-over period.
        start, end, _index = new_employee._get_work_year_for_date(
            date(2026, 6, 1))
        self.assertEqual(start, date(2026, 1, 10))
        self.assertEqual(end, date(2027, 1, 9))

    def test_transfer_reset_work_year(self):
        """reset: the transferred work-year balance starts a new work year at
        the transfer date (the new employee's hire_date is the transfer date)."""
        self._skip_if_no_balance()
        annual = self.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        self.env['hr.vacation.balance'].create({
            'employee_id': self.source_employee.id,
            'leave_type_id': annual.id,
            'period_start': date(2026, 1, 10),
            'period_end': date(2027, 1, 9),
            'period_index': 7,
            'entitled_days': 24,
        })
        wizard = self._make_wizard(vacation_transfer_mode='transfer',
                                   vacation_period_mode='reset')
        wizard.action_transfer()

        new_bal = self._new_balance_of(annual)
        self.assertTrue(new_bal)
        # New work year anchored to the transfer date (2026-05-01).
        self.assertEqual(new_bal.period_start, date(2026, 5, 1))
        self.assertEqual(new_bal.carried_over, 24)
        new_employee = self.source_employee.next_employee_id
        self.assertEqual(new_employee.hire_date, date(2026, 5, 1))
        # No carried anchor: the work year runs from the new hire date.
        self.assertFalse(new_employee.vacation_anchor_date)

    def test_transfer_calendar_type(self):
        """A calendar-type balance transfers with the same calendar period,
        regardless of the work-year mode."""
        self._skip_if_no_balance()
        social = self.env.ref(
            'l10n_ua_hr_holidays.leave_type_social_children')
        self.env['hr.vacation.balance'].create({
            'employee_id': self.source_employee.id,
            'leave_type_id': social.id,
            'period_start': date(2026, 1, 1),
            'period_end': date(2026, 12, 31),
            'period_index': 2026,
            'entitled_days': 10,
        })
        wizard = self._make_wizard(vacation_transfer_mode='transfer',
                                   vacation_period_mode='reset')
        wizard.action_transfer()

        new_bal = self._new_balance_of(social)
        self.assertTrue(new_bal)
        self.assertEqual(new_bal.period_start, date(2026, 1, 1))
        self.assertEqual(new_bal.period_end, date(2026, 12, 31))
        self.assertEqual(new_bal.carried_over, 10)
