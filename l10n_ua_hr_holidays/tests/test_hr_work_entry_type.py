from odoo.tests.common import TransactionCase


class TestHrLeaveType(TransactionCase):
    """Tests for hr.work.entry.type Ukrainian extensions"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_WORK_ENTR_1',
            'name': 'Test Annual Leave',
            'ua_leave_category': 'annual_basic',
            'annual_days': 24,
            'is_calendar_days': True,
            'is_transferable': True,
            'max_transfer_days': 12,
            'requires_experience': True,
            'min_experience_months': 6,
            'is_paid': True,
            'payment_source': 'employer',
            'min_continuous_days': 14,
        })

    def test_leave_type_creation(self):
        """Test that leave type is created with UA fields"""
        self.assertEqual(self.leave_type.ua_leave_category, 'annual_basic')
        self.assertEqual(self.leave_type.annual_days, 24)
        self.assertTrue(self.leave_type.is_calendar_days)
        self.assertTrue(self.leave_type.is_transferable)
        self.assertEqual(self.leave_type.max_transfer_days, 12)
        self.assertTrue(self.leave_type.requires_experience)
        self.assertEqual(self.leave_type.min_experience_months, 6)
        self.assertTrue(self.leave_type.is_paid)
        self.assertEqual(self.leave_type.payment_source, 'employer')
        self.assertEqual(self.leave_type.min_continuous_days, 14)

    def test_leave_type_defaults(self):
        """Test default values for leave type"""
        leave_type = self.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_WORK_ENTR_2',
            'name': 'Test Default Leave',
        })
        self.assertTrue(leave_type.is_calendar_days)
        self.assertTrue(leave_type.is_transferable)
        self.assertEqual(leave_type.annual_days, 24)
        self.assertEqual(leave_type.min_experience_months, 6)
        self.assertTrue(leave_type.is_paid)
        self.assertEqual(leave_type.payment_source, 'employer')
        self.assertEqual(leave_type.min_continuous_days, 14)

    def test_leave_type_categories(self):
        """Test all UA leave categories can be set"""
        categories = [
            'annual_basic', 'annual_additional', 'educational', 'creative',
            'social', 'unpaid', 'maternity', 'childcare', 'sick', 'other'
        ]
        for category in categories:
            leave_type = self.env['hr.work.entry.type'].create({
                # `code` is unique per country since Odoo 20.
                'code': f'UA_T_CAT_{category.upper()}',
                'name': f'Test {category}',
                'ua_leave_category': category,
            })
            self.assertEqual(leave_type.ua_leave_category, category)

    def test_payment_sources(self):
        """Test all payment sources can be set"""
        sources = ['employer', 'fss', 'mixed']
        for source in sources:
            leave_type = self.env['hr.work.entry.type'].create({
                'code': f'UA_T_SRC_{source.upper()}',
                'name': f'Test {source}',
                'payment_source': source,
            })
            self.assertEqual(leave_type.payment_source, source)

    def test_company_default_leave_type(self):
        """Типовий вид відпустки тепер належить компанії, а не виду.

        hr.work.entry.type у Odoo 20 прив'язана до країни, тож прапорець
        на ній означав би «типовий для всіх компаній країни». Поле на
        res.company і унікальне саме по собі, і не зачіпає сусідів.
        """
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'ТЕСТ Друга'})
        lt_a = self.env['hr.work.entry.type'].create({
            'name': 'Default A', 'code': 'UA_TEST_DEF_A'})
        lt_b = self.env['hr.work.entry.type'].create({
            'name': 'Default B', 'code': 'UA_TEST_DEF_B'})

        company_a.l10n_ua_default_leave_type_id = lt_a
        company_b.l10n_ua_default_leave_type_id = lt_b
        self.assertEqual(company_a.l10n_ua_default_leave_type_id, lt_a)
        self.assertEqual(company_b.l10n_ua_default_leave_type_id, lt_b,
                         'вибір однієї компанії не змінює вибір іншої')

        # Нове значення просто замінює попереднє — знімати прапорці
        # з інших видів більше не треба.
        company_a.l10n_ua_default_leave_type_id = lt_b
        self.assertEqual(company_a.l10n_ua_default_leave_type_id, lt_b)

        company_a.l10n_ua_default_leave_type_id = False
        self.assertFalse(company_a.l10n_ua_default_leave_type_id)
