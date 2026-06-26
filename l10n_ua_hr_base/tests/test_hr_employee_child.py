# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged
from datetime import date
from dateutil.relativedelta import relativedelta

from .common import TestHrUaBase


@tagged('post_install', '-at_install')
class TestHrEmployeeChild(TestHrUaBase):
    """Test hr.employee.child model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Parent Employee',
            'company_id': cls.company.id,
        })

    def _create_child(self, **kwargs):
        """Helper to create test child."""
        vals = {
            'employee_id': self.employee.id,
            'name': 'Test Child',
            'birthday': date.today() - relativedelta(years=10),
        }
        vals.update(kwargs)
        return self.env['hr.employee.child'].create(vals)

    def test_child_creation(self):
        """Test basic child record creation."""
        child = self._create_child(
            name='John Jr.',
            birthday=date(2015, 5, 20),
            gender='male',
        )

        self.assertEqual(child.name, 'John Jr.')
        self.assertEqual(child.gender, 'male')
        self.assertEqual(child.employee_id, self.employee)

    def test_child_age_computation(self):
        """Test age computed field."""
        # Child born 10 years ago
        child = self._create_child(
            birthday=date.today() - relativedelta(years=10),
        )
        self.assertEqual(child.age, 10)

        # Child born 5 years and 6 months ago
        child2 = self._create_child(
            name='Child 2',
            birthday=date.today() - relativedelta(years=5, months=6),
        )
        self.assertEqual(child2.age, 5)  # Age in full years

        # Newborn (less than 1 year)
        child3 = self._create_child(
            name='Baby',
            birthday=date.today() - relativedelta(months=6),
        )
        self.assertEqual(child3.age, 0)

    def test_child_is_dependent_default(self):
        """Test that is_dependent defaults to True."""
        child = self._create_child()
        self.assertTrue(child.is_dependent)

    def test_child_is_disabled(self):
        """Test is_disabled field."""
        child = self._create_child(is_disabled=True, disability_group='2')
        self.assertTrue(child.is_disabled)
        self.assertEqual(child.disability_group, '2')

    def test_child_is_disabled_requires_group(self):
        """Disabled child without group must raise ValidationError."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._create_child(is_disabled=True)

    def test_child_rnokpp_validation(self):
        """Test RNOKPP validation for child."""
        ChildModel = self.env['hr.employee.child']

        # Valid RNOKPP
        valid_rnokpp = self.generate_valid_rnokpp('123456789')
        self.assertTrue(ChildModel._validate_rnokpp(valid_rnokpp))

        # Invalid RNOKPP
        self.assertFalse(ChildModel._validate_rnokpp('1234567890'))
        self.assertFalse(ChildModel._validate_rnokpp('123'))
        self.assertFalse(ChildModel._validate_rnokpp(''))

    def test_child_birth_certificate(self):
        """Test birth certificate number field."""
        child = self._create_child(
            birth_certificate_number='I-AB №123456',
        )
        self.assertEqual(child.birth_certificate_number, 'I-AB №123456')

    def test_child_cascade_delete(self):
        """Test that children are deleted when employee is deleted."""
        child = self._create_child()
        child_id = child.id

        # Delete employee
        self.employee.unlink()

        # Child should be deleted too
        self.assertFalse(
            self.env['hr.employee.child'].search([('id', '=', child_id)])
        )

    def test_multiple_children(self):
        """Test employee with multiple children."""
        child1 = self._create_child(name='Child 1', birthday=date(2015, 1, 1))
        child2 = self._create_child(name='Child 2', birthday=date(2018, 6, 15))
        child3 = self._create_child(name='Child 3', birthday=date(2020, 12, 25))

        self.assertEqual(len(self.employee.children_ids), 3)
        self.assertEqual(self.employee.children_count, 3)

    def test_children_ordering(self):
        """Test that children are ordered by birthday desc."""
        child1 = self._create_child(name='Oldest', birthday=date(2010, 1, 1))
        child2 = self._create_child(name='Middle', birthday=date(2015, 1, 1))
        child3 = self._create_child(name='Youngest', birthday=date(2020, 1, 1))

        children = self.env['hr.employee.child'].search([
            ('employee_id', '=', self.employee.id)
        ])

        # Should be ordered by birthday desc (youngest first)
        self.assertEqual(children[0].name, 'Youngest')
        self.assertEqual(children[1].name, 'Middle')
        self.assertEqual(children[2].name, 'Oldest')
