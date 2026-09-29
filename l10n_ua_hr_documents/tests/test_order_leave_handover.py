"""The upgrade that hands the time-off link over — and the one that loses it.

`leave_id` and `holiday_status_id` now belong to l10n_ua_hr_holidays. Where
that module is installed the pre-migration hands the external ids over and the
values stay put. Where it is not, the fields are gone and the end-of-load
cleanup drops their columns; what an officer must not lose with them is which
time off an order was issued for, so the post-migration writes it into the
chatter while the column is still readable.
"""

import importlib.util
import os
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOrderLeaveHandover(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = os.path.join(
            os.path.dirname(__file__), '..', 'migrations', '19.0.1.2.0',
            'post-migration.py')
        spec = importlib.util.spec_from_file_location(
            'l10n_ua_hr_documents_19_1_2_0_post', path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def setUp(self):
        super().setUp()
        if 'leave_id' not in self.env['hr.order']._fields:
            # This module declares nothing about time off any more: without
            # l10n_ua_hr_holidays there is no link to lose, and the migration
            # has nothing to read.
            self.skipTest('l10n_ua_hr_holidays is not installed')
        self.employee = self.env['hr.employee'].create({
            'name': 'Коваленко Марія Петрівна',
            'company_id': self.env.company.id,
        })
        leave_type = self.env['hr.leave.type'].search(
            [('company_id', 'in', (self.env.company.id, False))], limit=1)
        self.leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': date(2025, 6, 2),
            'request_date_to': date(2025, 6, 6),
        })
        self.order = self.env['hr.order'].create({
            'order_type': 'vacation',
            'employee_id': self.employee.id,
            'date': date(2025, 6, 1),
            'subject': 'Відпустка',
            'company_id': self.env.company.id,
            'leave_id': self.leave.id,
        })
        # The link has to be in the column: the migration reads it with SQL,
        # the way it will have to on a database where the field is gone.
        self.env.flush_all()

    def _messages_on_order(self):
        self.order.invalidate_recordset(['message_ids'])
        return self.order.message_ids

    def test_nothing_is_said_while_the_link_keeps_its_owner(self):
        """l10n_ua_hr_holidays installed: the fields changed hands and kept
        their values, so there is nothing to rescue and nothing to say."""
        before = len(self._messages_on_order())

        self.script.migrate(self.env.cr, '19.0.1.1.1')

        self.assertEqual(len(self._messages_on_order()), before)

    def test_the_link_is_written_down_before_the_column_is_dropped(self):
        """Without that module the column goes with the field. The note is the
        last chance to record what it held."""
        # Only for this transaction: the module is installed in the test
        # database, and what is being tested is the database where it is not.
        self.env.cr.execute(
            "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
            ('l10n_ua_hr_holidays',))
        before = len(self._messages_on_order())

        self.script.migrate(self.env.cr, '19.0.1.1.1')

        messages = self._messages_on_order()
        self.assertEqual(len(messages), before + 1)
        body = messages[0].body
        self.assertIn(str(self.leave.id), body,
                      'the note must name the time off it is about')
        self.assertIn(self.employee.name, body)

    def test_a_fresh_install_is_left_alone(self):
        """`version` is empty on an install: there is no old database to fix."""
        self.env.cr.execute(
            "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
            ('l10n_ua_hr_holidays',))
        before = len(self._messages_on_order())

        self.script.migrate(self.env.cr, None)

        self.assertEqual(len(self._messages_on_order()), before)
