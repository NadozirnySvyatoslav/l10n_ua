from odoo import api, fields, models

# Стокові податки плану рахунків ua_psbo (модуль Odoo l10n_ua) зі ставкою 0,
# які за самим відсотком не відрізнити від 0 % експорту (#560). Шукаємо за
# xmlid шаблону, а не за назвою: назви перекладаються й їх правлять.
L10N_UA_STOCK_VAT_KINDS = {
    'sale_tax_template_vat20_psbo': 'taxable',
    'sale_tax_template_vat14_psbo': 'taxable',
    'sale_tax_template_vat7_psbo': 'taxable',
    'sale_tax_template_vat0_psbo': 'zero',
    'sale_tax_template_vat_free_psbo': 'exempt',
    'sale_tax_template_vat_not_psbo': 'not_object',
    'purchase_tax_template_vat20_psbo': 'taxable',
    'purchase_tax_template_vat14_psbo': 'taxable',
    'purchase_tax_template_vat7_psbo': 'taxable',
    'purchase_tax_template_vat0_psbo': 'zero',
    'purchase_tax_template_vat_free_psbo': 'exempt',
    'purchase_tax_template_vat_not_psbo': 'not_object',
}


class AccountTax(models.Model):
    _inherit = 'account.tax'

    ua_tax_type = fields.Selection(
        selection=[
            ('pdfo', 'PDFO (Personal Income Tax)'),
            ('vz', 'VZ (Military Tax)'),
            ('esv', 'ESV (Unified Social Contribution)'),
            ('pdv', 'PDV (VAT)'),
            ('ep', 'EP (Single Tax)'),
            ('profit', 'Profit Tax'),
            ('other', 'Other'),
        ],
        string='UA Tax Type',
    )
    # Вид ставки ПДВ (#560, рішення №3 реєстру). Відсоток податку не каже,
    # чи 0 % — це експорт (код 902), звільнення (903, р.5.1) чи операція, що
    # не є об'єктом (не йде в ПН, р.5). Порожнє поле — стара логіка за
    # відсотком, тож бази, де заповнення не відбулося, поводяться як раніше.
    l10n_ua_vat_kind = fields.Selection(
        selection=[
            ('taxable', 'Taxable (20/14/7 %)'),
            ('zero', 'Zero rate (0 %, code 902)'),
            ('exempt', 'Exempt (code 903)'),
            ('not_object', 'Not an object of VAT'),
        ],
        string='VAT Kind',
        help='Kind of the VAT rate for tax invoices and the VAT return. '
             'Empty: determined by the tax percentage.',
    )
    ua_tax_code = fields.Char(
        string='Tax Code',
        help='Tax code for reporting',
    )
    ua_budget_code_id = fields.Many2one(
        'l10n_ua.budget.code',
        string='Budget Code',
        help='Budget classification code for payment',
    )

    @api.model
    def _l10n_ua_fill_vat_kind(self, companies=None):
        """Проставити вид ставки стоковим податкам ua_psbo.

        Лише там, де поле порожнє: ручні правки бухгалтера не затираємо
        (як із КСПОВО в #670). Податки знаходимо за xmlid
        ``account.<company_id>_<шаблон>``, які створює завантаження плану.
        """
        domain = [('module', '=', 'account'), ('model', '=', 'account.tax')]
        names = []
        for company in (companies if companies is not None
                        else self.env['res.company'].search([])):
            names += ['%s_%s' % (company.id, tmpl) for tmpl in L10N_UA_STOCK_VAT_KINDS]
        if not names:
            return
        imd = self.env['ir.model.data'].search(domain + [('name', 'in', names)])
        for rec in imd:
            kind = L10N_UA_STOCK_VAT_KINDS[rec.name.split('_', 1)[1]]
            tax = self.browse(rec.res_id).exists()
            if tax and not tax.l10n_ua_vat_kind:
                tax.l10n_ua_vat_kind = kind


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo, force_create=True):
        res = super()._load(template_code, company, install_demo, force_create=force_create)
        self.env['account.tax']._l10n_ua_fill_vat_kind(company)
        return res
