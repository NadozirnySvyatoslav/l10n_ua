from . import models

def pre_init_hook(env):
    """
    Handle existing records in hr_vacation_balance where company_id is NULL
    before making the company_id field required=True.
    """
    env.cr.execute("SELECT to_regclass('hr_vacation_balance')")
    if env.cr.fetchone()[0]:
        env.cr.execute("""
            UPDATE hr_vacation_balance 
            SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1) 
            WHERE company_id IS NULL;
        """)

