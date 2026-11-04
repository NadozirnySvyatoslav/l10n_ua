from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang


class AccountMove(models.Model):
    _inherit = 'account.move'

    tax_invoice_ids = fields.One2many(
        'l10n_ua.tax.invoice',
        'move_id',
        string='Податкові накладні',
    )
    tax_invoice_count = fields.Integer(
        string='Кількість ПН',
        compute='_compute_tax_invoice_count',
    )

    @api.depends('tax_invoice_ids')
    def _compute_tax_invoice_count(self):
        for move in self:
            move.tax_invoice_count = len(move.tax_invoice_ids)

    # Ставки ПДВ, передбачені ПКУ. Ключ — `amount` відсоткового податку.
    _L10N_UA_VAT_RATES = {20.0: '20', 14.0: '14', 7.0: '7', 0.0: '0'}

    @api.model
    def _l10n_ua_vat_rate_for_line(self, invoice_line):
        """Ставка ПДВ рядка ПН за податками рядка документа.

        Повертає 'exempt', якщо ПДВ на рядку немає взагалі. Раніше тут стояв
        дефолт '20', тобто рядок без ПДВ потрапляв у ПН як оподаткований за
        основною ставкою — помилка, яка завищує зобовʼязання.

        Розрізнити звільнення (ст. 197) і необ'єкт (ст. 196) за самим фактом
        відсутності податку неможливо; для цього потрібні окремі податки з
        явною ознакою.
        """
        return self._l10n_ua_vat_rate_from_taxes(invoice_line.tax_ids)

    @api.model
    def _l10n_ua_vat_rate_from_taxes(self, taxes):
        """Перший відсотковий податок зі ставкою ПКУ, інакше 'exempt'.

        Групу податків розкриваємо: ПДВ часто входить до групи разом з іншим
        податком (акциз, збір), і без цього кроку оподаткований рядок мовчки
        ставав би звільненим з нульовою сумою.
        """
        for tax in taxes:
            if tax.amount_type == 'group':
                rate = self._l10n_ua_vat_rate_from_taxes(tax.children_tax_ids)
                if rate != 'exempt':
                    return rate
            elif tax.amount_type == 'percent' and tax.amount in self._L10N_UA_VAT_RATES:
                return self._L10N_UA_VAT_RATES[tax.amount]
        return 'exempt'

    def _l10n_ua_settlement_dates(self):
        """Дати всіх фактичних погашень документа, за зростанням.

        Рахуємо із зіставлення рядків розрахунків, а не з
        `matched_payment_ids`: погашення випискою напряму, залік кредит-ноти
        чи взаємозалік не мають об'єкта `account.payment`, і касовий метод
        вважав би такий документ неоплаченим — з відмовою створити ПН на
        операцію, за якою зобов'язання вже виникло.

        Дата — це дата проводки з того боку зіставлення, тобто самого
        платежу. Не `max_date` часткового зіставлення: там пізніша з двох
        дат, і передоплата отримала б дату рахунка замість дати грошей.

        Критерій — саме факт погашення рядка розрахунків, а не стан платежу:
        чернетка нічого не зіставляє й сюди не потрапляє в принципі.

        Зарахованим вважається будь-яке зіставлення, бо п. 187.10 визнає не
        лише кошти, а й «інші види компенсацій» — залік, бартер, погашення
        кредит-нотою. Списання безнадійного боргу під це не підпадає, але
        відрізнити його від заліку можна хіба що за наміром користувача, а
        зайва ПН на списаний борг — менша шкода, ніж пропущене зобов'язання
        за заліком.
        """
        self.ensure_one()
        settlement_lines = self.line_ids.filtered(
            lambda l: l.account_id.account_type in (
                'asset_receivable', 'liability_payable'))
        # Курсова різниця — окремий документ із рядком на тому ж рахунку, і
        # він теж зіставляється з рахунком. Без цього відсіювання валютний
        # рахунок, погашений одним платежем, виглядав би як два надходження.
        # Ядро вже вміє це рахувати — беремо його поле, а не свій фільтр.
        counterparts = settlement_lines.reconciled_lines_excluding_exchange_diff_ids
        # Кілька зіставлень однією датою — це одне надходження для ПН: одна
        # накладна на цю дату опише їх коректно.
        return sorted(set(counterparts.mapped('date')))

    def _l10n_ua_first_payment_date(self):
        """Дата найранішого фактичного погашення або False, якщо його немає."""
        self.ensure_one()
        dates = self._l10n_ua_settlement_dates()
        return dates[0] if dates else False

    def _l10n_ua_tax_invoice_rule(self):
        """Правило, за яким визначається дата ПН для цієї операції.

        Правило визнання визначає дату лише **наших власних** ПН:

        * вхідна ПН — чужий документ, її дату склав постачальник за своїм
          правилом. Наша неоплата не може бути перешкодою: ПН від
          постачальника вже існує, а касовий метод впливає на період
          податкового кредиту, а не на її дату;
        * РК складається на дату коригуючої події — повернення товару чи
          коштів, зміни ціни. Дата першої події оригіналу тут ні до чого,
          бо від дати РК рахується власний строк реєстрації в ЄРПН.

        В обох випадках дата береться з документа ('document').
        """
        self.ensure_one()
        if self.move_type in ('in_invoice', 'in_refund', 'out_refund'):
            return 'document'
        # Прапорець належить самому підприємству, а не його контактам: режим
        # оподаткування єдиний для юрособи, тож читаємо з комерційного
        # партнера — інакше рахунок на контакт-дитину пропустив би касовий
        # метод повз увагу.
        partner = self.commercial_partner_id.with_company(self.company_id)
        if partner.l10n_ua_vat_cash_method:
            return 'cash'
        return 'first_event'

    def _l10n_ua_tax_invoice_date(self):
        """Дата ПН за правилом визнання, застосовним до цієї операції.

        Касовий метод (п. 187.10 ПКУ): дата руху коштів. Поки оплати немає,
        податкове зобовʼязання не виникло і ПН складати нема на що. Надходжень
        може бути кілька, і на кожне складається своя ПН зі своєю датою
        (`_l10n_ua_cash_settlements`); тут — дата першої з них.

        Перша подія (загальне правило, ст. 187): раніша з дати відвантаження
        і дати оплати. Дату відвантаження беремо як дату документа —
        окремого обліку відвантажень тут немає, і для післяоплати це та сама
        дата; для передоплати раніший саме платіж, тому й порівнюємо.
        """
        self.ensure_one()
        rule = self._l10n_ua_tax_invoice_rule()
        doc_date = self.invoice_date or self.date
        if rule == 'document':
            return doc_date

        settlements = self._l10n_ua_settlement_dates()

        if rule == 'cash':
            if not settlements:
                self._l10n_ua_raise_cash_unpaid()
            return settlements[0]

        # Перша подія. Післяоплата дати не зсуває: перша подія — відвантаження,
        # і одна ПН на повну суму документа його описує.
        if not settlements or settlements[0] >= doc_date:
            return doc_date

        # Передоплата стала першою подією. Одна ПН тут правильна тільки якщо
        # аванс покриває документ повністю; часткова передоплата вимагає двох
        # ПН — на аванс і на відвантаження решти.
        self._l10n_ua_check_single_tax_invoice_fits(settlements)
        return settlements[0]

    def _l10n_ua_raise_cash_unpaid(self):
        raise UserError(_(
            'За контрагентом «%s» застосовується касовий метод ПДВ, '
            'тож ПН складається за датою оплати. Документ ще не оплачений.',
            self.commercial_partner_id.display_name))

    def _l10n_ua_check_single_tax_invoice_fits(self, settlements):
        """Відмовитись, якщо однією ПН операцію коректно не описати.

        Діє для першої події: ПН там одна на весь документ, а ПКУ прив'язує
        зобов'язання до події і її суми. Збігається це лише тоді, коли подія
        одна й покриває документ повністю. Інакше вийшла б ПН на повну суму
        датою першої події — завищене зобов'язання в одному періоді й
        порожнеча в наступному. Для касового методу поділ по надходженнях
        реалізовано (#255); часткову передоплату за першою подією (ПН на аванс
        + ПН на відвантаження решти) — ще ні, і доти відмова з поясненням
        чесніша за мовчки виданий некоректний податковий документ.
        """
        self.ensure_one()
        if len(settlements) > 1:
            raise UserError(_(
                'Документ погашений кількома надходженнями (%(count)s). На кожну '
                'подію складається окрема ПН на її суму, а такого поділу ще не '
                'реалізовано — вийшла б одна ПН на повну суму документа датою '
                'першого надходження. Заведіть ПН вручну.',
                count=len(settlements)))
        if not self.currency_id.is_zero(self.amount_residual):
            raise UserError(_(
                'Документ оплачений частково: залишок %(residual)s. ПН складається '
                'на суму події, а не документа, і такого поділу ще не реалізовано. '
                'Складіть ПН після повної оплати або заведіть її вручну.',
                residual=formatLang(self.env, self.amount_residual,
                                    currency_obj=self.currency_id)))

    # ------------------------------------------------------------------
    # Касовий метод: ПН на кожне надходження (п. 187.10 ПКУ, #255)
    # ------------------------------------------------------------------

    def _l10n_ua_cash_settlements(self):
        """Погашення документа з частками, які вони покривають, за порядком.

        Повертає список словників ``partial``, ``date``, ``payment_move``,
        ``share_before``, ``share_after``: частка документа (з ПДВ, у валюті
        документа), покрита до цього погашення і разом із ним.

        Набір погашень той самий, що в `_l10n_ua_settlement_dates`: будь-яке
        зіставлення рядка розрахунків, крім курсової різниці. Порядок — за
        датою надходження, далі за id, тобто стабільний між викликами: від
        нього залежить розкладання копійок, і повторний виклик має дати ті
        самі суми, що й перший.
        """
        self.ensure_one()
        settlement_lines = self.line_ids.filtered(
            lambda l: l.account_id.account_type in (
                'asset_receivable', 'liability_payable'))
        partials = settlement_lines.matched_debit_ids | settlement_lines.matched_credit_ids
        exchange_moves = partials.exchange_move_id

        entries = []
        for partial in partials:
            own_is_debit = partial.debit_move_id in settlement_lines
            counterpart = partial.credit_move_id if own_is_debit else partial.debit_move_id
            if counterpart.move_id in exchange_moves:
                continue
            amount = (partial.debit_amount_currency if own_is_debit
                      else partial.credit_amount_currency)
            entries.append({
                'partial': partial,
                'date': counterpart.date,
                'payment_move': counterpart.move_id,
                'amount': amount,
            })
        entries.sort(key=lambda e: (e['date'], e['partial'].id))

        total = abs(sum(settlement_lines.mapped('amount_currency')))
        covered = 0.0
        for entry in entries:
            entry['share_before'] = covered / total if total else 0.0
            covered += entry['amount']
            entry['share_after'] = covered / total if total else 0.0
        return entries

    def _l10n_ua_split_bases(self, ilines, share_before, share_after):
        """База кожного рядка ПН для надходження, що покриває частку документа.

        Розподіл пропорційний: надходження з ПДВ покриває однакову частку
        кожного рядка. Рахуємо кумулятивно — база рядка в цій ПН є різницею
        округлених «покрито разом із цим надходженням» і «покрито до нього».
        Так після повної оплати сума баз рядка по всіх ПН дорівнює рядку
        документа до копійки, скільки б надходжень не було.

        Підсумок ПН так само дорівнює округленій частці підсумку документа, а
        копійчану різницю між ним і сумою рядків гасить останній рядок із
        ненульовою сумою (на нульовому вона зникла б: база там — кількість ×
        нульова ціна).
        """
        currency = self.company_currency_id
        subtotals = {iline: iline.balance * self.direction_sign for iline in ilines}

        def portion(amount):
            return (currency.round(amount * share_after)
                    - currency.round(amount * share_before))

        bases = {iline: portion(subtotal) for iline, subtotal in subtotals.items()}
        absorbers = ilines.filtered(lambda l: not currency.is_zero(subtotals[l]))
        if absorbers:
            last = absorbers[-1]
            target = portion(sum(subtotals.values()))
            others = sum(base for iline, base in bases.items() if iline != last)
            bases[last] = currency.round(target - others)
        return bases

    def _l10n_ua_tax_invoice_line_vals(self, share=None, bases=None):
        """Рядки ПН з рядків документа.

        Без ``bases`` — на повну суму документа. З ``bases`` (касовий метод)
        — на суму надходження: ціна лишається фактичною ціною постачання, а
        кількість зменшується пропорційно, бо гр. 7 ПН — ціна одиниці, і
        «розрізати» треба саме обсяг, за який надійшли кошти.
        """
        # Фільтр саме `display_type == 'product'`: у Odoo 17+ звичайний рядок
        # має display_type 'product', а не порожній, тож умова `not display_type`
        # (написана під Odoo <=16) відкидала геть усі рядки й ПН виходила
        # порожньою. `invoice_line_ids` містить ще секції та примітки — їм у ПН
        # робити нічого.
        # РК зменшує зобов'язання: за Порядком 1307 у гр. 6 стоїть від'ємна
        # кількість при незмінній ціні. Доки цикл не виконувався, гілка refund
        # була безпечно порожньою; тепер вона створює документ, і без знаку РК
        # збільшував би зобов'язання замість зменшувати.
        sign = -1 if self.move_type in ('out_refund', 'in_refund') else 1

        line_vals = []
        seq = 10
        for iline in self._l10n_ua_tax_invoice_source_lines():
            # Суму беремо з проводки, а не з `price_subtotal`: ПН завжди у
            # гривні (`currency_id` — related на валюту компанії), а проводка
            # вже перерахована за курсом документа. Перераховувати кожен рядок
            # окремо не варто — округлення дало б копійчаний дрейф від суми
            # документа. `direction_sign` знімає знак дебету/кредиту.
            subtotal = iline.balance * self.direction_sign
            # Ціна за одиницю після знижки й без ПДВ. Зберігати сирий
            # `price_unit` не можна: рядок ПН рахує базу як quantity *
            # price_unit, і знижка зникла б. Для <CINA> в XML ЄРПН потрібна
            # саме фактична ціна постачання.
            net_unit_price = subtotal / iline.quantity if iline.quantity else 0.0
            quantity = iline.quantity
            if bases is not None:
                quantity = (iline.quantity * bases[iline] / subtotal if subtotal
                            else iline.quantity * share)

            line_vals.append((0, 0, {
                'sequence': seq,
                'product_id': iline.product_id.id if iline.product_id else False,
                'name': iline.name or iline.product_id.display_name or '',
                # гр. 3.1 для товару, гр. 3.3 для послуги — за Порядком
                # 1307 п. 16 рядок несе рівно один із двох кодів, тож який
                # саме, вирішує тип номенклатури, а не наявність значення.
                **iline.product_id._l10n_ua_product_codes(),
                'quantity': sign * quantity,
                'uom_id': iline.product_uom_id.id if iline.product_uom_id else False,
                'price_unit': net_unit_price,
                'vat_rate': self._l10n_ua_vat_rate_for_line(iline),
            }))
            seq += 10
        return line_vals

    def _l10n_ua_tax_invoice_source_lines(self):
        return self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _l10n_ua_tax_invoice_base_vals(self, invoice_type, is_refund):
        # Стороною операції в ПН є юрособа, а не її контакт: ІПН і назва
        # для ЄРПН належать саме їй. Рахунок можна виставити на
        # «Бухгалтерію» чи адресу доставки — у ПН має піти підприємство,
        # інакше <BUYER_IPN> вийде порожнім і документ не зареєструється.
        number = self.env['ir.sequence'].next_by_code(
            f'l10n_ua.tax.invoice.{invoice_type}') or _('Новий')
        return {
            'invoice_type': invoice_type,
            'doc_type': 'rk' if is_refund else 'pn',
            'number': number,
            'vat_method': self._l10n_ua_tax_invoice_rule(),
            'partner_id': self.commercial_partner_id.id,
            'company_id': self.company_id.id,
            'move_id': self.id,
        }

    def _l10n_ua_create_cash_tax_invoices(self):
        """Скласти ПН на кожне ще не покрите надходження (п. 187.10 ПКУ).

        Покритим вважається погашення, до якого прив'язана нескасована ПН.
        Повторний виклик складає лише відсутні ПН, тож кнопку можна тиснути
        після кожної нової оплати.

        ПН, що втратила зіставлення (оплату розʼєднали з рахунком), блокує
        генерацію: чи зобов'язання за тими коштами лишилось, чи їх
        повернули, чи перенесли на інший рахунок, вирішує людина. Мовчки
        скласти нову ПН на повторне зіставлення означало б задвоїти
        зобов'язання.
        """
        self.ensure_one()
        TaxInvoice = self.env['l10n_ua.tax.invoice']
        active = self.tax_invoice_ids.filtered(lambda t: t.state != 'cancelled')
        orphans = active.filtered(lambda t: t.vat_method == 'cash' and not t.partial_reconcile_id)
        if orphans:
            raise UserError(_(
                'ПН %(names)s складено за касовим методом, але вона не пов\'язана '
                'з жодним чинним погашенням цього документа (зіставлення з оплатою '
                'скасовано або ПН складено до поділу по надходженнях). Щоб не '
                'задвоїти зобов\'язання, нові ПН не складаються: скасуйте зайву ПН '
                'або оформіть її коригування, і повторіть.',
                names=', '.join(orphans.mapped('name'))))

        settlements = self._l10n_ua_cash_settlements()
        if not settlements:
            self._l10n_ua_raise_cash_unpaid()

        covered = active.partial_reconcile_id
        missing = [s for s in settlements if s['partial'] not in covered]
        if not missing:
            raise UserError(_(
                'На всі надходження за цим документом ПН уже складено.'))

        # Скасування ПН могло ще не потрапити в БД, а унікальний індекс
        # (одна чинна ПН на погашення) перевіряє саме стан у БД.
        TaxInvoice.flush_model(['state', 'partial_reconcile_id'])
        ilines = self._l10n_ua_tax_invoice_source_lines()
        created = TaxInvoice
        for settlement in missing:
            bases = self._l10n_ua_split_bases(
                ilines, settlement['share_before'], settlement['share_after'])
            share = settlement['share_after'] - settlement['share_before']
            vals = self._l10n_ua_tax_invoice_base_vals('issued', False)
            vals.update({
                'date': settlement['date'],
                'partial_reconcile_id': settlement['partial'].id,
                'payment_move_id': settlement['payment_move'].id,
                'line_ids': self._l10n_ua_tax_invoice_line_vals(share=share, bases=bases),
            })
            created |= TaxInvoice.create(vals)
        return created

    def action_create_tax_invoice(self):
        """Create a tax invoice (ПН) from customer/vendor invoice.

        За касовим методом — по одній ПН на кожне ще не покрите надходження.
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Створити ПН можна тільки для проведеного документа.'))

        if self.move_type in ('out_invoice', 'out_refund'):
            invoice_type = 'issued'
        elif self.move_type in ('in_invoice', 'in_refund'):
            invoice_type = 'received'
        else:
            raise UserError(_('ПН можна створити тільки для рахунків.'))

        if self._l10n_ua_tax_invoice_rule() == 'cash':
            return self._l10n_ua_tax_invoices_action(
                self._l10n_ua_create_cash_tax_invoices())

        is_refund = self.move_type in ('out_refund', 'in_refund')
        # Дата ПН — дата виникнення податкового зобовʼязання, а не день
        # натискання кнопки: від неї рахується строк реєстрації в ЄРПН і
        # період декларації. Визначаємо до номера: відмова тут не має
        # спалювати номер у послідовності.
        date = self._l10n_ua_tax_invoice_date()
        vals = self._l10n_ua_tax_invoice_base_vals(invoice_type, is_refund)
        vals.update({
            'date': date,
            'line_ids': self._l10n_ua_tax_invoice_line_vals(),
        })
        if is_refund:
            # РК без посилання на оригінал ЄРПН не приймає. Знаходимо ПН
            # сторнованого документа; якщо її немає (ПН виписана поза
            # системою), поле лишається порожнім для ручного заповнення.
            original = self.reversed_entry_id.tax_invoice_ids[:1]
            vals.update({
                'original_invoice_id': original.id,
                'reason': self.ref or '',
            })

        tax_invoice = self.env['l10n_ua.tax.invoice'].create(vals)
        return self._l10n_ua_tax_invoices_action(tax_invoice)

    def _l10n_ua_tax_invoices_action(self, tax_invoices):
        if len(tax_invoices) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'l10n_ua.tax.invoice',
                'res_id': tax_invoices.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Податкові накладні'),
            'res_model': 'l10n_ua.tax.invoice',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', tax_invoices.ids)],
            'target': 'current',
        }

    def action_view_tax_invoices(self):
        """Open related tax invoices."""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Податкові накладні'),
            'res_model': 'l10n_ua.tax.invoice',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }
        if self.tax_invoice_count == 1:
            action['view_mode'] = 'form'
            action['res_id'] = self.tax_invoice_ids[0].id
        return action
