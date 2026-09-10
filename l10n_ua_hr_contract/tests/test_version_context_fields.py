"""UA fields on the employee card follow the version being looked at.

The versions timeline widget reloads the employee with `version_id` in the
context. The UA fields used to be related through `current_version_id`, so they
kept showing today's version while the native ones switched — and an edit made
in that state landed on today's version instead of the one on screen.

Covers reading and writing, the one2many case in both directions (adding and
editing a line through the card), plus a guard that the groups on the card
still mirror the ones on hr.version.
"""

from datetime import date

from odoo.tests import tagged

from .common import ContractTestCase

# Every UA field the card re-declares over the delegation, with the group it
# must carry. Kept as a literal list so that adding a field to hr.employee
# without its group makes the guard test fail rather than pass silently.
VERSION_RELATED_FIELDS = [
    'contract_type_ua', 'is_main_workplace', 'is_part_time', 'part_time_type',
    'work_mode', 'work_rate', 'tariff_grade_id', 'work_conditions',
    'work_conditions_class', 'work_conditions_subclass',
    'additional_vacation_days', 'diia_city_employee', 'hire_order_number',
    'hire_order_date', 'termination_order_number', 'termination_order_date',
    'termination_reason_ua_id', 'probation_period_days', 'probation_end_date',
    'allowance_ids', 'salary_change_ids', 'amendment_ids',
]


@tagged('post_install', '-at_install')
class TestVersionContextFields(ContractTestCase):
    """UA fields resolve against the version in the context, not today's."""

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee()
        # The version born with the employee is dated today, so it is pushed
        # into the past to become the historical one; the version created next
        # is the most recent one that is already in force, hence the current.
        self.old_version = self.employee.version_ids
        self.assertEqual(len(self.old_version), 1)
        self.old_version.write({
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'contract_type_ua': 'permanent',
            'hire_order_number': 'OLD-001',
        })
        self.current_version = self._create_version(
            employee=self.employee,
            date_version=date(2024, 6, 1),
            contract_date_start=date(2024, 1, 1),
            contract_type_ua='fixed_term',
            hire_order_number='CUR-001',
        )
        self.employee.invalidate_recordset()
        self.assertEqual(self.employee.current_version_id,
                         self.current_version)

    def test_read_without_context_uses_current_version(self):
        """Плаїн картка показує сьогоднішню версію."""
        self.assertEqual(self.employee.contract_type_ua, 'fixed_term')
        self.assertEqual(self.employee.hire_order_number, 'CUR-001')

    def test_read_in_version_context_uses_that_version(self):
        """Обрана в таймлайні версія — те, що показує картка."""
        employee = self.employee.with_context(
            version_id=self.old_version.id)
        self.assertEqual(employee.contract_type_ua, 'permanent')
        self.assertEqual(employee.hire_order_number, 'OLD-001')

    def test_write_in_version_context_hits_that_version(self):
        """Правка в контексті версії пише саме в неї, поточна недоторкана."""
        self.employee.with_context(
            version_id=self.old_version.id).contract_type_ua = 'civil'
        self.assertEqual(self.old_version.contract_type_ua, 'civil')
        self.assertEqual(self.current_version.contract_type_ua, 'fixed_term')

    def test_write_without_context_hits_current_version(self):
        """Без контексту пишемо в сьогоднішню версію."""
        self.employee.contract_type_ua = 'seasonal'
        self.assertEqual(self.current_version.contract_type_ua, 'seasonal')
        self.assertEqual(self.old_version.contract_type_ua, 'permanent')

    def test_one2many_follows_version_context(self):
        """Надбавки належать обраній версії, а не сьогоднішній."""
        old_allowance = self.env['hr.version.allowance'].create({
            'version_id': self.old_version.id,
            'allowance_type_id': self.allowance_seniority.id,
            'calculation_method': 'fixed',
            'amount': 500.0,
        })
        current_allowance = self.env['hr.version.allowance'].create({
            'version_id': self.current_version.id,
            'allowance_type_id': self.allowance_hazard.id,
            'calculation_method': 'fixed',
            'amount': 700.0,
        })
        self.employee.invalidate_recordset()
        self.assertEqual(self.employee.allowance_ids, current_allowance)
        self.assertEqual(
            self.employee.with_context(
                version_id=self.old_version.id).allowance_ids,
            old_allowance)

    def test_one2many_write_in_version_context_hits_that_version(self):
        """Надбавка, додана з картки в контексті версії, лягає саме в неї."""
        self.employee.with_context(version_id=self.old_version.id).write({
            'allowance_ids': [(0, 0, {
                'allowance_type_id': self.allowance_seniority.id,
                'calculation_method': 'fixed',
                'amount': 500.0,
            })],
        })

        self.assertEqual(len(self.old_version.allowance_ids), 1)
        self.assertEqual(self.old_version.allowance_ids.amount, 500.0)
        self.assertFalse(self.current_version.allowance_ids)

    def test_one2many_edit_in_version_context_hits_that_version(self):
        """Правка наявної надбавки в контексті версії не чіпає поточну."""
        old_allowance = self.env['hr.version.allowance'].create({
            'version_id': self.old_version.id,
            'allowance_type_id': self.allowance_seniority.id,
            'calculation_method': 'fixed',
            'amount': 500.0,
        })
        current_allowance = self.env['hr.version.allowance'].create({
            'version_id': self.current_version.id,
            'allowance_type_id': self.allowance_seniority.id,
            'calculation_method': 'fixed',
            'amount': 700.0,
        })
        self.employee.invalidate_recordset()

        self.employee.with_context(version_id=self.old_version.id).write({
            'allowance_ids': [(1, old_allowance.id, {'amount': 900.0})],
        })

        self.assertEqual(old_allowance.amount, 900.0)
        self.assertEqual(current_allowance.amount, 700.0)

    def test_one2many_write_without_context_hits_current_version(self):
        """Без контексту надбавка з картки лягає в сьогоднішню версію."""
        self.employee.write({
            'allowance_ids': [(0, 0, {
                'allowance_type_id': self.allowance_hazard.id,
                'calculation_method': 'fixed',
                'amount': 700.0,
            })],
        })

        self.assertEqual(len(self.current_version.allowance_ids), 1)
        self.assertFalse(self.old_version.allowance_ids)

    def test_fields_mirror_version_groups(self):
        """Права на UA-полях картки збігаються з правами на версії."""
        employee_fields = self.env['hr.employee']._fields
        version_fields = self.env['hr.version']._fields
        for name in VERSION_RELATED_FIELDS:
            with self.subTest(field=name):
                field = employee_fields[name]
                self.assertEqual(field.related, f'version_id.{name}')
                self.assertTrue(field.inherited)
                self.assertEqual(field.groups, version_fields[name].groups)
                self.assertEqual(field.readonly, version_fields[name].readonly)
