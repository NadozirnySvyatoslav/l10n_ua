"""Company settings for Ukrainian accounting: payment approval, cash limit."""

from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_payment_approval_enabled = fields.Boolean(
        string='Затвердження платежів',
        default=False,
        help='Увімкнути вимогу затвердження платежів вище порогу',
    )
    l10n_ua_payment_approval_threshold = fields.Monetary(
        string='Поріг затвердження',
        default=50000,
        currency_field='currency_id',
        help='Платежі на суму більше цього порогу потребують затвердження головного бухгалтера',
    )

    # --- Cash limit control ---
    l10n_ua_cash_limit_enabled = fields.Boolean(
        string='Контроль ліміту каси',
        default=False,
        help='Увімкнути контроль залишку каси на кінець робочого дня',
    )
    l10n_ua_cash_limit = fields.Monetary(
        string='Ліміт каси',
        default=10000,
        currency_field='currency_id',
        help='Максимально допустимий залишок готівки в касі на кінець робочого дня',
    )

    # --- Advance report (авансовий звіт) posting ---
    l10n_ua_advance_journal_id = fields.Many2one(
        'account.journal',
        string='Журнал авансових звітів',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help='Журнал для проводок авансових звітів. '
             'Якщо не задано — береться перший загальний журнал компанії.',
    )
    l10n_ua_advance_account_id = fields.Many2one(
        'account.account',
        string='Рахунок підзвітних осіб (372)',
        check_company=True,
        help='Рахунок розрахунків з підзвітними особами (372), '
             'на кредит якого списуються витрати. '
             'Якщо не задано — шукається рахунок із кодом 372.',
    )
    l10n_ua_advance_expense_account_id = fields.Many2one(
        'account.account',
        string='Типовий рахунок витрат авансзвіту',
        check_company=True,
        help='Рахунок витрат за замовчуванням для рядків авансового звіту '
             '(використовується, якщо в рядку не вказано власний рахунок).',
    )

    # --- Курсові різниці (переоцінка валютних коштів) ---
    l10n_ua_fx_gain_op_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Дохід від операційної курсової різниці (714)',
        help='Рахунок для додатних операційних курсових різниць.',
    )
    l10n_ua_fx_loss_op_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Втрати від операційної курсової різниці (945)',
        help='Рахунок для відʼємних операційних курсових різниць.',
    )
    l10n_ua_fx_gain_nonop_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Дохід від неопераційної курсової різниці (744)',
        help='Рахунок для додатних неопераційних курсових різниць.',
    )
    l10n_ua_fx_loss_nonop_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Втрати від неопераційної курсової різниці (974)',
        help='Рахунок для відʼємних неопераційних курсових різниць.',
    )

    # --- Витрати / доходи майбутніх періодів (#372) ---
    l10n_ua_deferred_expense_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Deferred Expense Account (39)',
        help='Default account for deferred expenses. If empty, the first '
             'account with code 39… is used.',
    )
    l10n_ua_deferred_revenue_account_id = fields.Many2one(
        'account.account', check_company=True,
        string='Deferred Revenue Account (69)',
        help='Default account for deferred revenue. If empty, the first '
             'account with code 69… is used.',
    )
    l10n_ua_deferral_journal_id = fields.Many2one(
        'account.journal',
        string='Deferral Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help='Journal for deferral recognition entries. If empty, the first '
             'miscellaneous journal of the company is used.',
    )

    def _l10n_ua_is_ukrainian(self):
        """Whether Ukrainian accounting rules apply to this company.

        The module may be installed in a database that also hosts companies of
        other countries; UA-specific documents and checks must not touch them.

        Tolerates an empty recordset: computes run on new records whose
        company_id is not set yet.
        """
        return len(self) == 1 and self.country_id.code == 'UA'
