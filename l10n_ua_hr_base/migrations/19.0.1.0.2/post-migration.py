from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    """
    Copies the value from barcode to employee_number for existing employees
    if the employee_number field is empty.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    # Using a direct SQL query for performance on large databases
    cr.execute("""
        UPDATE hr_employee 
        SET employee_number = barcode 
        WHERE (employee_number IS NULL OR employee_number = '') 
          AND barcode IS NOT NULL;
    """)
