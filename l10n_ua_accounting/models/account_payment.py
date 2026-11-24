"""Extension of account.payment for Ukrainian cash orders (PKO/VKO) and bank payment orders (ПД)."""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    """Extend account.payment for Ukrainian cash orders and bank payment orders.

    In Ukrainian accounting:
    - PKO (ПКО) = Прибутковий касовий ордер = Cash Receipt Order (inbound)
    - VKO (ВКО) = Видатковий касовий ордер = Cash Disbursement Order (outbound)
    - ПД = Платіжне доручення = Bank Payment Order (outbound bank transfer)

    Inherits analytic.mixin to provide analytic_distribution field with the
    standard Odoo widget, search method, and gin index — plays nicely with
    Enterprise Edition modules that may also extend account.payment.
    """
    _name = 'account.payment'
    _inherit = ['account.payment', 'analytic.mixin']

    # --- Cash Order fields ---
    ua_cash_order_number = fields.Char(
        string='Cash Order Number',
        copy=False,
        help='Ukrainian cash order number (auto-generated for cash journals)',
    )
    ua_payment_basis = fields.Char(
        string='Payment Basis',
        help='Basis/reason for this cash operation (підстава)',
    )
    ua_cash_person = fields.Char(
        string='Cash Person',
        help='Person who received (for VKO) or paid (for PKO) cash',
    )
    ua_person_document = fields.Char(
        string='Person Document',
        help='Document of the person (passport, ID card)',
    )
    ua_appendix = fields.Char(
        string='Appendix',
        help='List of appendix documents (додатки)',
    )
    ua_cash_order_type = fields.Selection(
        selection=[
            ('pko', 'PKO (Receipt)'),
            ('vko', 'VKO (Disbursement)'),
            ('other', 'Other'),
        ],
        string='Cash Order Type',
        compute='_compute_ua_cash_order_type',
        store=True,
    )
    is_ua_cash_order = fields.Boolean(
        string='Is Cash Order',
        compute='_compute_is_ua_cash_order',
        store=True,
    )

    # --- Approval workflow fields ---
    ua_approval_required = fields.Boolean(
        string='Потребує затвердження',
        compute='_compute_ua_approval_required',
        store=True,
    )
    ua_approved = fields.Boolean(
        string='Затверджено',
        tracking=True,
        copy=False,
    )
    ua_approved_by = fields.Many2one(
        'res.users',
        string='Затвердив',
        readonly=True,
        copy=False,
    )
    ua_approved_date = fields.Datetime(
        string='Дата затвердження',
        readonly=True,
        copy=False,
    )

    # --- Bank Payment Order fields ---
    ua_payment_order_number = fields.Char(
        string='Payment Order Number',
        copy=False,
        help='Ukrainian payment order number (auto-generated for bank journals)',
    )
    ua_payment_purpose = fields.Text(
        string='Payment Purpose',
        help='Призначення платежу — payment purpose text for the bank',
    )
    ua_payment_order_type = fields.Selection(
        selection=[
            ('pd', 'ПД (Платіжне доручення)'),
            ('other', 'Other'),
        ],
        string='Payment Order Type',
        compute='_compute_ua_payment_order_type',
        store=True,
    )
    is_ua_payment_order = fields.Boolean(
        string='Is Payment Order',
        compute='_compute_is_ua_payment_order',
        store=True,
    )

    # analytic_distribution provided by analytic.mixin (Json + widget + gin index)
    # Override label to Ukrainian via attribute redefinition
    analytic_distribution = fields.Json(
        string='Аналітичний розподіл',
        compute='_compute_analytic_distribution',
        search='_search_analytic_distribution',
        store=True, copy=True, readonly=False,
        help='Стаття руху грошових коштів та інша аналітика. '
             'Передається на counterpart та write-off рядки журнальних проводок '
             'при підтвердженні платежу. Не передається на ліквідну (cash) сторону.',
    )

    # --- Cash order computes ---

    @api.depends('journal_id', 'journal_id.type', 'company_id.country_id')
    def _compute_is_ua_cash_order(self):
        for payment in self:
            payment.is_ua_cash_order = (
                payment.journal_id.type == 'cash'
                and payment.company_id._l10n_ua_is_ukrainian()
            )

    @api.depends('payment_type', 'journal_id.type', 'company_id.country_id')
    def _compute_ua_cash_order_type(self):
        for payment in self:
            if (payment.journal_id.type == 'cash'
                    and payment.company_id._l10n_ua_is_ukrainian()):
                if payment.payment_type == 'inbound':
                    payment.ua_cash_order_type = 'pko'
                else:
                    payment.ua_cash_order_type = 'vko'
            else:
                payment.ua_cash_order_type = 'other'

    # --- Payment order computes ---

    @api.depends('journal_id', 'journal_id.type', 'payment_type', 'company_id.country_id')
    def _compute_is_ua_payment_order(self):
        for payment in self:
            payment.is_ua_payment_order = (
                payment.journal_id.type == 'bank'
                and payment.payment_type == 'outbound'
                and payment.company_id._l10n_ua_is_ukrainian()
            )

    @api.depends('payment_type', 'journal_id.type', 'company_id.country_id')
    def _compute_ua_payment_order_type(self):
        for payment in self:
            if (payment.journal_id.type == 'bank'
                    and payment.payment_type == 'outbound'
                    and payment.company_id._l10n_ua_is_ukrainian()):
                payment.ua_payment_order_type = 'pd'
            else:
                payment.ua_payment_order_type = 'other'

    # --- Outstanding account of cash orders ---

    def _get_outstanding_account(self, payment_type):
        """ПКО/ВКО проводяться прямо по рахунку каси (301), без транзиту.

        Стокове ядро бере рахунок неоплачених надходжень/платежів компанії, а в
        плані ua_psbo це субрахунки 311 (банк): ПКО ставало Дт 311 замість
        Дт 301, і касова книга, ліміт каси та ОСВ по 301 показували 0 (#598).
        Каса не має виписки, яку треба звіряти, тож платіж одразу «оплачено».
        Рахунок, явно вказаний у способі оплати журналу, має пріоритет — його
        ядро бере в _compute_outstanding_account_id, сюди черга не доходить.

        Лише коли рахунок журналу — клас 30 «Готівка» (301/302): журнал типу
        «Каса» на іншому рахунку (підзвіт, транзит, 333 тощо) лишається на
        стоковій логіці з рахунком неоплачених і звіркою.
        """
        journal = self.journal_id
        account = journal.default_account_id
        if (journal.type == 'cash' and account
                and self.company_id._l10n_ua_is_ukrainian()
                and (account.with_company(self.company_id).code or '').startswith('30')):
            return account
        return super()._get_outstanding_account(payment_type)

    # --- Analytic distribution propagation ---

    def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
        """Inject analytic_distribution into counterpart and write-off lines.

        Cash (liquidity) side does not get analytics — стаття руху грошових коштів
        applies to the expense/income side of the cash transaction. Core returns a
        flat list [liquidity, counterpart, *write_offs]; the liquidity line is the
        one booked on the outstanding account.
        """
        line_vals_list = super()._prepare_move_line_default_vals(
            write_off_line_vals=write_off_line_vals, force_balance=force_balance,
        )
        if not self.analytic_distribution:
            return line_vals_list
        for line_vals in line_vals_list:
            if line_vals.get('account_id') == self.outstanding_account_id.id:
                continue
            line_vals.setdefault('analytic_distribution', dict(self.analytic_distribution))
        return line_vals_list

    # --- Create with auto-sequencing ---

    @api.model_create_multi
    def create(self, vals_list):
        """Generate Ukrainian document numbers for cash and bank payments."""
        for vals in vals_list:
            journal_id = vals.get('journal_id')
            if not journal_id:
                continue
            journal = self.env['account.journal'].browse(journal_id)
            company = journal.company_id
            if vals.get('company_id'):
                company = self.env['res.company'].browse(vals['company_id'])
            if not company._l10n_ua_is_ukrainian():
                continue
            payment_type = vals.get('payment_type', 'inbound')

            # Cash order number
            if not vals.get('ua_cash_order_number') and journal.type == 'cash':
                if payment_type == 'inbound':
                    sequence = journal.ua_pko_sequence_id
                else:
                    sequence = journal.ua_vko_sequence_id
                if sequence:
                    vals['ua_cash_order_number'] = sequence.next_by_id()

            # Payment order number
            if not vals.get('ua_payment_order_number') and journal.type == 'bank' and payment_type == 'outbound':
                sequence = journal.ua_pd_sequence_id
                if sequence:
                    vals['ua_payment_order_number'] = sequence.next_by_id()

        return super().create(vals_list)

    # --- Print actions ---

    def action_print_pko(self):
        """Print PKO (Cash Receipt Order) form KO-1."""
        self.ensure_one()
        return self.env.ref('l10n_ua_accounting.action_report_pko').report_action(self)

    def action_print_vko(self):
        """Print VKO (Cash Disbursement Order) form KO-2."""
        self.ensure_one()
        return self.env.ref('l10n_ua_accounting.action_report_vko').report_action(self)

    def action_print_payment_order(self):
        """Print Payment Order (Платіжне доручення)."""
        self.ensure_one()
        return self.env.ref('l10n_ua_accounting.action_report_payment_order').report_action(self)

    # --- Approval workflow ---

    @api.depends('amount', 'payment_type', 'company_id.l10n_ua_payment_approval_enabled',
                 'company_id.l10n_ua_payment_approval_threshold')
    def _compute_ua_approval_required(self):
        for payment in self:
            company = payment.company_id
            if (company.l10n_ua_payment_approval_enabled
                    and payment.payment_type == 'outbound'
                    and payment.amount > company.l10n_ua_payment_approval_threshold):
                payment.ua_approval_required = True
            else:
                payment.ua_approval_required = False

    def action_approve(self):
        """Approve payment — головбух sign-off."""
        for payment in self:
            if not payment.ua_approval_required:
                continue
            payment.write({
                'ua_approved': True,
                'ua_approved_by': self.env.uid,
                'ua_approved_date': fields.Datetime.now(),
            })
            # Remove pending approval activities
            payment.activity_ids.filtered(
                lambda a: a.activity_type_id == self.env.ref(
                    'mail.mail_activity_data_todo', raise_if_not_found=False
                )
            ).action_done()
            payment.message_post(body=_(
                'Платіж затверджено користувачем %s',
                self.env.user.name,
            ))

    def action_reject(self):
        """Reject/revoke payment approval."""
        for payment in self:
            payment.write({
                'ua_approved': False,
                'ua_approved_by': False,
                'ua_approved_date': False,
            })
            payment.message_post(body=_(
                'Затвердження скасовано користувачем %s',
                self.env.user.name,
            ))

    def action_post(self):
        """Override to block posting if approval required but not given,
        and warn if cash limit would be exceeded."""
        analytic_required = self.env.user.has_group('analytic.group_analytic_accounting')
        for payment in self:
            if payment.ua_approval_required and not payment.ua_approved:
                payment._schedule_approval_activity()
                raise UserError(_(
                    'Платіж на суму %(amount)s %(currency)s потребує затвердження '
                    'головного бухгалтера (поріг: %(threshold)s %(currency)s).',
                    amount=payment.amount,
                    currency=payment.currency_id.name,
                    threshold=payment.company_id.l10n_ua_payment_approval_threshold,
                ))
            if (analytic_required
                    and payment.is_ua_cash_order
                    and not payment.analytic_distribution):
                raise UserError(_(
                    "Для касового ордеру вкажіть аналітичний розподіл "
                    "(статтю руху грошових коштів)."
                ))
        result = super().action_post()
        # Check cash limit after posting
        self._check_cash_limit_warning()
        return result

    def _check_cash_limit_warning(self):
        """Warn if cash balance exceeds the configured limit after posting."""
        for payment in self:
            company = payment.company_id
            if not company.l10n_ua_cash_limit_enabled:
                continue
            if payment.journal_id.type != 'cash':
                continue
            balance = payment.journal_id._get_cash_balance()
            if balance > company.l10n_ua_cash_limit:
                payment.message_post(body=_(
                    '⚠️ Увага! Залишок каси (%(balance)s %(currency)s) '
                    'перевищує ліміт (%(limit)s %(currency)s).',
                    balance='%.2f' % balance,
                    currency=company.currency_id.name,
                    limit='%.2f' % company.l10n_ua_cash_limit,
                ))

    def _schedule_approval_activity(self):
        """Schedule mail.activity for account manager to approve."""
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        # Find account managers
        manager_group = self.env.ref('account.group_account_manager', raise_if_not_found=False)
        if not manager_group:
            return
        managers = manager_group.users
        if not managers:
            return
        # Schedule for first manager (головбух)
        manager = managers[0]
        for payment in self:
            existing = payment.activity_ids.filtered(
                lambda a: a.activity_type_id == activity_type
                and a.user_id == manager
            )
            if existing:
                continue
            payment.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.id,
                summary=_('Затвердити платіж на суму %s %s',
                          payment.amount, payment.currency_id.name),
                note=_('Платіж контрагенту %(partner)s на суму %(amount)s %(currency)s '
                       'перевищує поріг %(threshold)s %(currency)s і потребує затвердження.',
                       partner=payment.partner_id.name or '',
                       amount=payment.amount,
                       currency=payment.currency_id.name,
                       threshold=payment.company_id.l10n_ua_payment_approval_threshold),
            )
