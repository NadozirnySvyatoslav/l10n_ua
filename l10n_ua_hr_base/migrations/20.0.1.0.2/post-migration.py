
def migrate(cr, version):
    """
    Copies the value from barcode to employee_number for existing employees
    if the employee_number field is empty.
    """
    # Using a direct SQL query for performance on large databases
    cr.execute("""
    UPDATE hr_employee
       SET employee_number = barcode
     WHERE COALESCE(employee_number, '') = ''
       AND COALESCE(barcode, '') <> ''
    """)
