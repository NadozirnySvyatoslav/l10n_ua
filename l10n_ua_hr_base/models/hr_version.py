import logging

from odoo import models, api, fields, _
from odoo.exceptions import UserError

from .hr_employee import REGISTRATION_ADDRESS_MAP

_logger = logging.getLogger(__name__)


def _l10n_ua_has_rate(env, currency, company, date):
    """Whether the rate table can answer for `currency` on `date`.

    `_convert` quietly falls back to 1.0 when it finds nothing, which turns a
    missing rate into a number that looks calculated. Two places have to refuse
    instead — the wage on a version and the salary on a staffing line — so the
    lookup they both refuse on lives here: the latest rate on or before the
    date, belonging to this company or shared by all of them.

    Each caller raises its own message: only the caller knows whose money it
    is, and "the wage of X" and "the staffing line Y" send an officer to two
    different screens.
    """
    return bool(env['res.currency.rate'].search_count([
        ('currency_id', '=', currency.id),
        ('company_id', 'in', [company.id, False]),
        ('name', '<=', date),
    ]))


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def _l10n_ua_wage_in_company_currency(self, date=None, wage=None):
        """Оклад у валюті компанії на задану дату.

        `wage` зберігається в тій валюті, яку задано у версії, а всі
        українські розрахунки — гривневі. Хто читає `wage` напряму, той
        мовчки вважає число гривнями: оклад 1000 USD давав аванс 500 грн,
        середньоденну для відпустки 34 грн і таку саму довідку про доходи.

        Хелпер живе тут, у `l10n_ua_hr_base`, хоча поле валюти оголошує
        `l10n_ua_hr_salary`: модуль відпусток про зарплату не знає (спільний
        предок у них саме цей), а шість копій `hasattr` по місцях виклику —
        це шість місць, де наступна копія з'явиться непоміченою. Без модуля
        зарплати валюта окладу одна, тож `getattr` тут не хитрість, а
        єдиний чесний спосіб спитати «а чи є взагалі валютний оклад».

        Дата потрібна, бо курс змінюється: аванс середини місяця, відпустка
        в липні та довідка за минулий рік мають рахуватись кожне за своїм
        курсом, а не за сьогоднішнім.

        `wage` may be passed in, and then the field is not read at all. That
        matters to whoever has just written it: the field is restricted to
        `hr.group_hr_manager`, and reading it back would mean asking the ORM
        for something it is entitled to refuse. Whoever could write it could
        read it.
        """
        self.ensure_one()
        wage = (self.wage if wage is None else wage) or 0.0
        currency = getattr(self, 'salary_currency_id', False)
        company = self.company_id or self.env.company
        company_currency = company.currency_id
        if not wage or not currency or not company_currency \
                or currency == company_currency:
            return wage

        date = date or fields.Date.context_today(self)
        if not _l10n_ua_has_rate(self.env, currency, company, date):
            raise UserError(_(
                'Оклад %(employee)s встановлено в %(currency)s, але курс цієї '
                'валюти на %(date)s не заданий. Без курсу оклад потрапив би в '
                'розрахунок як гривневий. Внесіть курс у довідник валют.',
                employee=self.employee_id.name or '',
                currency=currency.name,
                date=fields.Date.to_string(date)))

        # round=False з тієї ж причини, що й у розрахунковому листку:
        # інакше курс стискається до копійки й дає похибку на кожній
        # тисячі окладу.
        return currency._convert(
            wage, company_currency, company, date, round=False)

    @api.constrains('country_id')
    def _check_ua_military_citizenship(self):
        """Mirror of the employee-side check, from where nationality lives.

        `country_id` is stored on the version, so setting a foreign
        nationality on an employee card writes hr.version and never triggers
        an hr.employee constraint. Only the current version counts — the
        employee's own `country_id` reads from it.
        """
        for version in self:
            employee = version.employee_id
            if employee and employee.current_version_id == version:
                employee._assert_military_matches_citizenship()

    def _sync_ua_registration_address(self):
        """Push the private address of the current version onto the employee.

        private_* physically lives here, not on hr.employee, so signing a new
        contract, changing a status or editing a version straight from the
        version list never goes through hr.employee.write(). Without this hook
        the registration block silently drifts away from the address it is
        supposed to mirror.

        Only the version that is currently authoritative counts: editing a past
        or future version must not rewrite today's registration address.
        """
        current = self.filtered(
            lambda version: version.employee_id
            and version.employee_id.current_version_id == version)
        current.employee_id._sync_registration_address_from_private()

    @api.model_create_multi
    def create(self, vals_list):
        versions = super().create(vals_list)
        versions._sync_ua_registration_address()
        return versions

    def write(self, vals):
        res = super().write(vals)
        if not REGISTRATION_ADDRESS_MAP.keys().isdisjoint(vals):
            self._sync_ua_registration_address()
        return res
