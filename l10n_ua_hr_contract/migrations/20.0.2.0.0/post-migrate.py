from odoo import api, SUPERUSER_ID
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Post-migration script for l10n_ua_hr_contract 20.0.2.0.0
    
    This migration moves data from hr.contract.ua to hr.version fields.
    """
    if not version:
        return

    _logger.info("Starting post-migration for l10n_ua_hr_contract 20.0.2.0.0")

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Check if old table exists
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'hr_contract_ua'
        )
    """)
    if not cr.fetchone()[0]:
        _logger.info("hr_contract_ua table does not exist, skipping data migration")
        return

    # Migrate data from hr.contract.ua to hr.version
    _logger.info("Migrating data from hr.contract.ua to hr.version...")

    cr.execute("""
        SELECT 
            c.id,
            c.employee_id,
            c.contract_type_ua,
            c.is_main_workplace,
            c.is_part_time,
            c.part_time_type,
            c.work_mode,
            c.working_hours_week,
            c.work_rate,
            c.probation_period_days,
            c.probation_end_date,
            c.staffing_line_id,
            c.tariff_grade_id,
            c.work_schedule_id,
            c.termination_reason_id,
            c.hire_order_number,
            c.hire_order_date,
            c.termination_order_number,
            c.termination_order_date,
            c.diia_city_employee,
            c.work_conditions,
            c.work_conditions_class,
            c.work_conditions_subclass,
            c.additional_vacation_days,
            c.date_start,
            c.wage
        FROM hr_contract_ua c
        WHERE c.state = 'open'
        ORDER BY c.date_start DESC
    """)

    contracts = cr.fetchall()
    migrated_count = 0

    for contract in contracts:
        (contract_id, employee_id, contract_type_ua, is_main_workplace, is_part_time,
         part_time_type, work_mode, working_hours_week, work_rate, probation_period_days,
         probation_end_date, staffing_line_id, tariff_grade_id, work_schedule_id,
         termination_reason_id, hire_order_number, hire_order_date, termination_order_number,
         termination_order_date, diia_city_employee, work_conditions, work_conditions_class,
         work_conditions_subclass, additional_vacation_days, date_start, wage) = contract

        # Find current version for employee
        cr.execute("""
            SELECT v.id 
            FROM hr_version v
            JOIN hr_employee e ON e.version_id = v.id
            WHERE e.id = %s
            LIMIT 1
        """, (employee_id,))

        result = cr.fetchone()
        if not result:
            _logger.warning(f"No version found for employee {employee_id}, skipping contract {contract_id}")
            continue

        version_id = result[0]

        # Update version with contract data
        cr.execute("""
            UPDATE hr_version SET
                contract_type_ua = %s,
                is_main_workplace = %s,
                is_part_time = %s,
                part_time_type = %s,
                work_mode = %s,
                working_hours_week = %s,
                work_rate = %s,
                probation_period_days = %s,
                probation_end_date = %s,
                staffing_line_id = %s,
                tariff_grade_id = %s,
                work_schedule_ua_id = %s,
                termination_reason_ua_id = %s,
                hire_order_number = %s,
                hire_order_date = %s,
                termination_order_number = %s,
                termination_order_date = %s,
                diia_city_employee = %s,
                work_conditions = %s,
                work_conditions_class = %s,
                work_conditions_subclass = %s,
                additional_vacation_days = %s,
                contract_date_start = COALESCE(contract_date_start, %s),
                wage = COALESCE(wage, %s)
            WHERE id = %s
        """, (
            contract_type_ua, is_main_workplace, is_part_time, part_time_type,
            work_mode, working_hours_week, work_rate, probation_period_days,
            probation_end_date, staffing_line_id, tariff_grade_id, work_schedule_id,
            termination_reason_id, hire_order_number, hire_order_date,
            termination_order_number, termination_order_date, diia_city_employee,
            work_conditions, work_conditions_class, work_conditions_subclass,
            additional_vacation_days, date_start, wage, version_id
        ))

        migrated_count += 1

    _logger.info(f"Migrated {migrated_count} contracts to hr.version")

    # Migrate allowances
    _logger.info("Migrating allowances...")
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'hr_contract_allowance'
        )
    """)
    if cr.fetchone()[0]:
        # Create hr_version_allowance table if needed
        cr.execute("""
            INSERT INTO hr_version_allowance (
                version_id, allowance_type_id, sequence, calculation_method,
                amount, percent, date_from, date_to, notes, create_uid, create_date, write_uid, write_date
            )
            SELECT 
                (SELECT v.id FROM hr_version v 
                 JOIN hr_employee e ON e.version_id = v.id 
                 WHERE e.id = c.employee_id LIMIT 1) as version_id,
                a.allowance_type_id,
                a.sequence,
                a.calculation_method,
                a.amount,
                a.percent,
                a.date_from,
                a.date_to,
                a.notes,
                a.create_uid,
                a.create_date,
                a.write_uid,
                a.write_date
            FROM hr_contract_allowance a
            JOIN hr_contract_ua c ON c.id = a.contract_id
            WHERE c.state = 'open'
        """)
        _logger.info("Allowances migrated")

    _logger.info("Post-migration completed")
