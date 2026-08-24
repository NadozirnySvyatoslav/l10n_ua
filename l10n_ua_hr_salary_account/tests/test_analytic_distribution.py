"""Аналітичний розподіл зарплатних витрат (#209)."""

from datetime import date

from odoo.tests import tagged
from odoo.addons.l10n_ua_hr_salary.tests.common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestSalaryAnalyticDistribution(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # У Odoo 19 hr.employee.department_id — related до version_id.department_id,
        # тож підрозділ (і, відповідно, payslip.department_id) береться з версії.
        cls.version.department_id = cls.department

        # --- Аналітичні рахунки (проєкти) ---
        cls.plan = cls.env['account.analytic.plan'].create({'name': 'Проєкти'})
        cls.aa1 = cls.env['account.analytic.account'].create({
            'name': 'Проєкт A', 'plan_id': cls.plan.id,
            'company_id': cls.company.id})
        cls.aa2 = cls.env['account.analytic.account'].create({
            'name': 'Проєкт B', 'plan_id': cls.plan.id,
            'company_id': cls.company.id})
        cls.dist_a = {str(cls.aa1.id): 100.0}
        cls.dist_b = {str(cls.aa2.id): 100.0}

        # --- План рахунків ---
        def acc(code, name, atype):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': atype,
                'company_ids': [(4, cls.company.id)]})
        cls.acc_expense = acc('9200A', 'Адмінвитрати ЗП', 'expense')
        cls.acc_661 = acc('6610A', 'ЗП до виплати', 'liability_payable')
        cls.acc_651 = acc('6510A', 'ЄСВ', 'liability_current')
        cls.acc_6411 = acc('6411A', 'ПДФО', 'liability_current')
        cls.acc_6415 = acc('6415A', 'Військовий збір', 'liability_current')

        cls.journal = cls.env['account.journal'].create({
            'name': 'Зарплата', 'type': 'general', 'code': 'SALA',
            'company_id': cls.company.id})

        # У БД може вже існувати конфіг компанії (unique per company) — оновлюємо.
        cfg_vals = {
            'salary_journal_id': cls.journal.id,
            'wages_payable_account_id': cls.acc_661.id,
            'pdfo_payable_account_id': cls.acc_6411.id,
            'military_tax_payable_account_id': cls.acc_6415.id,
            'esv_payable_account_id': cls.acc_651.id,
            'default_expense_account_id': cls.acc_expense.id,
        }
        cls.config = cls.env['hr.salary.account.config'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if cls.config:
            cls.config.write(cfg_vals)
        else:
            cls.config = cls.env['hr.salary.account.config'].create(
                dict(cfg_vals, company_id=cls.company.id))

    def _make_slip(self):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        slip.write({
            'scheduled_hours': 160.0, 'scheduled_days': 20,
            'worked_days': 20, 'worked_hours': 160.0,
        })
        return slip

    def _computed_slip(self):
        slip = self._make_slip()
        slip.action_compute_sheet()
        return slip

    # --- Резолвер розподілу ---

    def test_resolver_version_over_department(self):
        self.department.salary_analytic_distribution = self.dist_b
        self.version.salary_analytic_distribution = self.dist_a
        slip = self._make_slip()
        self.assertEqual(slip._get_salary_analytic_distribution(), self.dist_a)

    def test_resolver_department_fallback(self):
        self.version.salary_analytic_distribution = False
        self.department.salary_analytic_distribution = self.dist_b
        slip = self._make_slip()
        self.assertEqual(slip._get_salary_analytic_distribution(), self.dist_b)

    def test_resolver_none(self):
        self.version.salary_analytic_distribution = False
        self.department.salary_analytic_distribution = False
        slip = self._make_slip()
        self.assertFalse(slip._get_salary_analytic_distribution())

    # --- Проброс у рядки проводки ---

    def test_move_lines_carry_analytic(self):
        self.version.salary_analytic_distribution = self.dist_a
        slip = self._computed_slip()
        self.assertTrue(slip.gross_salary, 'Має бути ненульове нарахування')
        lines = slip._prepare_move_lines(self.config)
        # Витратні рядки (Дт рахунку витрат: ЗП + ЄСВ) несуть аналітику
        expense_lines = [l for l in lines
                         if l['account_id'] == self.acc_expense.id]
        self.assertTrue(expense_lines)
        for line in expense_lines:
            self.assertEqual(line.get('analytic_distribution'), self.dist_a)
        # Решта рядків (утримання/зобов'язання) — без аналітики
        for line in lines:
            if line['account_id'] != self.acc_expense.id:
                self.assertFalse(line.get('analytic_distribution'))

    def test_move_lines_no_analytic_when_unset(self):
        self.version.salary_analytic_distribution = False
        self.department.salary_analytic_distribution = False
        slip = self._computed_slip()
        lines = slip._prepare_move_lines(self.config)
        for line in lines:
            self.assertFalse(line.get('analytic_distribution'))

    # --- Групування у зведеній проводці ---

    def test_analytic_grouping_key(self):
        Run = self.env['hr.payslip.run']
        # Однаковий розподіл → однаковий ключ
        self.assertEqual(
            Run._analytic_key(self.dist_a),
            Run._analytic_key({str(self.aa1.id): 100.0}))
        # Різний розподіл → різні ключі (окремі рядки витрат)
        self.assertNotEqual(
            Run._analytic_key(self.dist_a), Run._analytic_key(self.dist_b))
        # Порожній розподіл → порожній ключ
        self.assertEqual(Run._analytic_key(False), ())
        self.assertEqual(Run._analytic_key({}), ())

    # --- Залежності віджета analytic_distribution ---

    def test_widget_reads_analytic_precision(self):
        """Віджет analytic_distribution дочитує analytic_precision з моделі.

        Поле salary_analytic_distribution показане цим віджетом у формах
        працівника і підрозділу. JS оголошує analytic_precision у
        fieldDependencies, тож web_read просить його на тій самій моделі —
        і без явного поля картка падає з «Invalid field 'analytic_precision'».
        """
        for record in (self.employee, self.version, self.department):
            with self.subTest(model=record._name):
                self.assertIn('analytic_precision', record._fields)
                value = record.read(['analytic_precision'])[0]
                self.assertIsInstance(value['analytic_precision'], int)
