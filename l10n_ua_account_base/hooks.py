"""Донесення плану рахунків П(С)БО до компаній, які вже працюють на `ua_psbo`.

Шаблон плану рахунків матеріалізується один раз — коли на компанію ставиться
локалізація. Для баз, де `l10n_ua` встановили раніше за цей модуль (тобто для
всіх наявних), самого `@template` замало: нові рахунки просто нікуди не
потраплять. Тому після встановлення проходимо по компаніях і доводимо план:

* створюємо рахунки, яких бракує (клас 0 і субрахунки з `PSBO_EXTRA_ACCOUNTS`);
* проставляємо аналітику там, де її ще не задано;
* налаштовуємо субконто «Контрагенти» / «Номенклатура» на рахунках з такою
  аналітикою — необовʼязкове, щоб не зламати жодної наявної проводки.

Назви стокових рахунків не переписуємо: їх міг поправити бухгалтер.

Ідемпотентно: повторний запуск нічого не дублює і не перетирає ручних змін.

`post_init_hook` спрацьовує тільки при встановленні модуля (`loading.py`,
`update_operation == 'install'`). Для баз, де модуль уже стоїть, те саме
викликає міграція поточної версії.
"""
import logging

from .models.template_ua_psbo import own_accounts, stock_account_analytics

_logger = logging.getLogger(__name__)

# ua_analytics_type → xmlid виду субконто, яким цю аналітику ведуть.
# Працівники — у bridge-модулі з hr, тут їх немає.
ANALYTICS_SUBCONTO = {
    'partner': 'l10n_ua_account_base.subconto_type_partner',
    'product': 'l10n_ua_account_base.subconto_type_product',
}


def _code_digits(env):
    # Коди в плані доповнюються нулями до code_digits (для ua_psbo це 6), тож
    # рахунок 01 має стати 010000 — інакше хук наплодив би дублікати поруч із
    # тими, що прийшли шаблоном. Полегшений `_get_chart_template_model_data`
    # тут не годиться: для 'template_data' функції повертають плаский словник
    # значень, а не xmlid → значення, і він на ньому падає.
    return int(env['account.chart.template']._get_chart_template_data('ua_psbo')
               ['template_data'].get('code_digits') or 6)


def _psbo_companies(env, companies=None):
    if companies is None:
        return env['res.company'].search([('chart_template', '=', 'ua_psbo')])
    return companies.filtered(lambda c: c.chart_template == 'ua_psbo')


def _company_accounts(env, company, codes):
    return env['account.account'].with_company(company).search([
        ('code', 'in', list(codes)),
        ('company_ids', 'parent_of', company.id),
    ])


def ensure_psbo_accounts(env, companies=None):
    """Створити відсутні рахунки модуля всім компаніям на плані `ua_psbo`."""
    digits = _code_digits(env)
    Account = env['account.account']
    for company in _psbo_companies(env, companies):
        wanted = {code.ljust(digits, '0'): values for code, values in own_accounts()}
        existing = set(_company_accounts(env, company, wanted).mapped('code'))
        missing = {code: vals for code, vals in wanted.items() if code not in existing}
        if not missing:
            continue
        Account.with_company(company).create([{
            **vals,
            'code': code,
            'company_ids': [(6, 0, [company.id])],
        } for code, vals in missing.items()])
        _logger.info('l10n_ua_account_base: додано %s рахунків П(С)БО для %s',
                     len(missing), company.display_name)


def ensure_account_analytics(env, companies=None):
    """Проставити аналітику стоковим рахункам, де її ще не задано."""
    digits = _code_digits(env)
    wanted = {code.ljust(digits, '0'): values
              for code, values in stock_account_analytics().items()}
    for company in _psbo_companies(env, companies):
        for account in _company_accounts(env, company, wanted):
            values = wanted[account.code]
            update = {}
            if values.get('ua_analytics_type') and account.ua_analytics_type in (False, 'none'):
                update['ua_analytics_type'] = values['ua_analytics_type']
            for flag in ('ua_is_currency', 'ua_is_quantity'):
                if values.get(flag) and not account[flag]:
                    update[flag] = True
            if update:
                account.write(update)


def ensure_account_subconto(env, companies=None):
    """Субконто за видом аналітики рахунку — лише де його ще немає.

    Субконто ставиться необовʼязковим: `_check_required_subconto` відхилив би
    кожну проводку на 631 чи 361, у якої значення субконто не заповнене, а
    рахунки-фактури заповнюють `partner_id`, не субконто.
    """
    Subconto = env['l10n_ua.account.subconto']
    types = {analytics: env.ref(xmlid, raise_if_not_found=False)
             for analytics, xmlid in ANALYTICS_SUBCONTO.items()}
    for company in _psbo_companies(env, companies):
        accounts = env['account.account'].with_company(company).search([
            ('company_ids', 'parent_of', company.id),
            ('ua_analytics_type', 'in', list(types)),
        ])
        vals = []
        for account in accounts:
            subconto_type = types[account.ua_analytics_type]
            if not subconto_type or account.subconto_ids.filtered(
                    lambda s, t=subconto_type: s.subconto_type_id == t):
                continue
            vals.append({
                'account_id': account.id,
                'subconto_type_id': subconto_type.id,
                'sequence': 10,
                'required': False,
            })
        if vals:
            Subconto.create(vals)


def ensure_psbo_chart(env, companies=None):
    """Довести план `ua_psbo` до Наказу № 291: рахунки, аналітика, субконто."""
    ensure_psbo_accounts(env, companies)
    ensure_account_analytics(env, companies)
    ensure_account_subconto(env, companies)


def ensure_offbalance_accounts(env):
    """Сумісність зі старими каталогами міграцій (клас 0 — частина плану)."""
    ensure_psbo_accounts(env)


def post_init_hook(env):
    ensure_psbo_chart(env)
