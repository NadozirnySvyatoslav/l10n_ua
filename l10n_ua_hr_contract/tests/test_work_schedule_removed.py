"""hr.work.schedule is gone for good (#213, phase 2).

Phase 1 moved the weekly norm onto the native resource.calendar; phase 2
deleted the UA models. These tests fail loudly if any part of them creeps
back — a stray field, an orphaned menu, or an access rule pointing at a model
that no longer exists.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWorkScheduleRemoved(TransactionCase):

    def test_models_are_gone(self):
        self.assertNotIn('hr.work.schedule', self.env)
        self.assertNotIn('hr.work.schedule.line', self.env)
        self.assertFalse(self.env['ir.model'].search([
            ('model', 'in', ('hr.work.schedule', 'hr.work.schedule.line')),
        ]))

    def test_version_fields_are_gone(self):
        version_fields = self.env['hr.version']._fields
        self.assertNotIn('work_schedule_ua_id', version_fields)
        self.assertNotIn('working_hours_week', version_fields)
        employee_fields = self.env['hr.employee']._fields
        self.assertNotIn('work_schedule_ua_id', employee_fields)
        self.assertNotIn('working_hours_week', employee_fields)

    def test_no_leftover_records(self):
        """No orphaned XML ids, ACLs or rules from the removed models."""
        leftovers = self.env['ir.model.data'].search([
            ('module', '=', 'l10n_ua_hr_contract'),
            ('name', 'like', 'work_schedule'),
        ])
        self.assertFalse(
            leftovers,
            'Leftover XML ids: %s' % leftovers.mapped('complete_name'))
        # Odoo 20 merged ir.model.access and ir.rule into ir.access.
        self.assertFalse(self.env['ir.access'].search([
            ('model_id.model', 'like', 'hr.work.schedule'),
        ]))

    def test_calendar_carries_the_norm(self):
        """The replacement is in place: the version reads its norm from the
        native calendar."""
        calendar = self.env['resource.calendar'].search(
            [('ua_code', '!=', False)], limit=1)
        self.assertTrue(
            calendar,
            'The predefined UA calendars must exist after the migration')
        self.assertIn('ua_schedule_type', calendar._fields)
