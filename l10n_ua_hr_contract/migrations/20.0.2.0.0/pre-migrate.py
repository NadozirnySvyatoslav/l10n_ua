from odoo import api, SUPERUSER_ID
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Pre-migration script for l10n_ua_hr_contract 20.0.2.0.0
    
    This migration moves data from hr.contract.ua to hr.version fields.
    The hr.contract.ua model is being deprecated in favor of extending hr.version.
    """
    if not version:
        return

    _logger.info("Starting pre-migration for l10n_ua_hr_contract 20.0.2.0.0")

    # Check if old table exists
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'hr_contract_ua'
        )
    """)
    if not cr.fetchone()[0]:
        _logger.info("hr_contract_ua table does not exist, skipping migration")
        return

    # Add new columns to hr_version if they don't exist
    columns_to_add = [
        ('contract_type_ua', 'VARCHAR'),
        ('is_main_workplace', 'BOOLEAN'),
        ('is_part_time', 'BOOLEAN'),
        ('part_time_type', 'VARCHAR'),
        ('work_mode', 'VARCHAR'),
        ('working_hours_week', 'FLOAT'),
        ('work_rate', 'FLOAT'),
        ('probation_period_days', 'INTEGER'),
        ('probation_end_date', 'DATE'),
        ('staffing_line_id', 'INTEGER'),
        ('tariff_grade_id', 'INTEGER'),
        ('work_schedule_ua_id', 'INTEGER'),
        ('termination_reason_ua_id', 'INTEGER'),
        ('hire_order_number', 'VARCHAR'),
        ('hire_order_date', 'DATE'),
        ('termination_order_number', 'VARCHAR'),
        ('termination_order_date', 'DATE'),
        ('diia_city_employee', 'BOOLEAN'),
        ('work_conditions', 'VARCHAR'),
        ('work_conditions_class', 'INTEGER'),
        ('work_conditions_subclass', 'INTEGER'),
        ('additional_vacation_days', 'INTEGER'),
    ]

    for col_name, col_type in columns_to_add:
        cr.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'hr_version' AND column_name = '{col_name}'
            )
        """)
        if not cr.fetchone()[0]:
            _logger.info(f"Adding column {col_name} to hr_version")
            default = "DEFAULT FALSE" if col_type == 'BOOLEAN' else ""
            if col_name == 'work_rate':
                default = "DEFAULT 1.0"
            elif col_name == 'working_hours_week':
                default = "DEFAULT 40.0"
            cr.execute(f"ALTER TABLE hr_version ADD COLUMN {col_name} {col_type} {default}")

    _logger.info("Pre-migration completed")
