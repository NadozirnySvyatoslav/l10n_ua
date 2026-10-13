"""Рахунок-фактура із замовлення на продаж. Усі реквізити в тестах вигадані."""
from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

REPORT = 'l10n_ua_doc_reports.action_report_rahunok_sale'
NBSP = '\u00a0'

# Fictitious requisites with valid checksums; bank MFO in the IBANs is 123456
SUPPLIER_EDRPOU = '11111116'
BUYER_EDRPOU = '22222221'
IBAN_UAH = 'UA781234560000026001234567890'
IBAN_OTHER = 'UA831234560000026009876543210'


@tagged('post_install', '-at_install', 'l10n_ua_doc_reports')
class TestRahunokSale(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The common test user is an accountant; orders need sales rights
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_salesman')
        cls.uah = cls.setup_other_currency('UAH')
        cls.eur = cls.setup_other_currency('EUR')
        cls.usd = cls.setup_other_currency('USD')
        cls.company_partner = cls.env.company.partner_id
        cls.company_partner.write({
            'l10n_ua_legal_address': False,
            'street': 'вул. Тестова, 1',
            'city': 'Київ',
            'edrpou': SUPPLIER_EDRPOU,
            'l10n_ua_chief_name': 'Тестенко Т.Т.',
            'l10n_ua_chief_position': 'Директор',
        })
        cls.bank = cls.env['res.bank'].create({'name': 'АТ «Тестовий банк»', 'bic': 'TESTUAUX'})
        # The foreign-currency account comes first: the report must not just take bank_ids[:1]
        cls.env['res.partner.bank'].create({
            'acc_number': IBAN_OTHER,
            'partner_id': cls.company_partner.id,
            'bank_id': cls.bank.id,
            'currency_id': cls.eur.id,
            'sequence': 1,
        })
        cls.env['res.partner.bank'].create({
            'acc_number': IBAN_UAH,
            'partner_id': cls.company_partner.id,
            'bank_id': cls.bank.id,
            'currency_id': cls.uah.id,
            'sequence': 2,
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'ТОВ «Тестовий покупець»',
            'is_company': True,
            'edrpou': BUYER_EDRPOU,
            'street': 'вул. Покупця, 2',
            'city': 'Львів',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Послуги з розробки', 'type': 'service', 'list_price': 1500,
        })
        cls.vat_20_included = cls.env['account.tax'].create({
            'name': 'ПДВ 20% у ціні (тест)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include_override': 'tax_included',
            'company_id': cls.env.company.id,
        })
        cls.pricelist_uah = cls.env['product.pricelist'].create({
            'name': 'UAH (тест)', 'currency_id': cls.uah.id,
        })
        cls.pricelist_usd = cls.env['product.pricelist'].create({
            'name': 'USD (тест)', 'currency_id': cls.usd.id,
        })

    def _order(self, lines=None, pricelist=None, **vals):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'pricelist_id': (pricelist or self.pricelist_uah).id,
            'date_order': '2026-10-13 10:00:00',
            'order_line': [(0, 0, line) for line in (lines or [{
                'product_id': self.product.id,
                'name': 'Послуги з розробки',
                'product_uom_qty': 10,
                'price_unit': 1500,
                'tax_ids': [(6, 0, [])],
            }])],
            **vals,
        })

    def _render(self, order):
        return self.env['ir.actions.report']._render_qweb_html(REPORT, order.ids)[0].decode()

    def test_bank_account_by_currency_and_mfo_from_iban(self):
        """Рахунок компанії у валюті замовлення; МФО з IBAN, а не SWIFT."""
        if 'ua_mfo' in self.bank._fields:
            self.bank.ua_mfo = False
        html = self._render(self._order())
        self.assertIn(IBAN_UAH, html)
        self.assertNotIn(IBAN_OTHER, html)
        self.assertIn('МФО 123456', html)
        self.assertNotIn('TESTUAUX', html)

    def test_report_lines_only_products(self):
        """Розділи, підрозділи й нотатки не друкуються як позиції."""
        order = self._order(lines=[
            {'display_type': 'line_section', 'name': 'Розділ'},
            {'display_type': 'line_subsection', 'name': 'Підрозділ'},
            {'product_id': self.product.id, 'name': 'Послуга', 'product_uom_qty': 1,
             'price_unit': 100, 'tax_ids': [(6, 0, [])]},
            {'display_type': 'line_note', 'name': 'Примітка'},
        ])
        self.assertEqual(order._get_ua_report_lines().mapped('name'), ['Послуга'])

    def test_price_unit_without_vat_for_tax_included(self):
        """Ціна без ПДВ для податку «у ціні»: кількість × ціна = сума без ПДВ."""
        order = self._order(lines=[{
            'product_id': self.product.id,
            'name': 'Послуга з ПДВ у ціні',
            'product_uom_qty': 3,
            'price_unit': 1200,
            'tax_ids': [(6, 0, self.vat_20_included.ids)],
        }])
        line = order._get_ua_report_lines()
        self.assertAlmostEqual(order._get_ua_line_price_unit_excl(line), 1000.0)
        self.assertAlmostEqual(line.price_subtotal, 3000.0)
        html = self._render(order)
        self.assertIn('Ціна без ПДВ, грн', html)
        self.assertIn('1%s000,00' % NBSP, html)   # unit price without VAT
        self.assertIn('3%s600,00' % NBSP, html)   # amount with VAT

    def test_render(self):
        order = self._order(lines=[{
            'product_id': self.product.id,
            'name': 'Послуги з розробки',
            'product_uom_qty': 1000,
            'price_unit': 1500,
            'tax_ids': [(6, 0, [])],
        }])
        html = self._render(order)
        self.assertIn('Рахунок-фактура № %s' % order.name, html)
        self.assertIn('від «13» жовтня 2026 р.', html)
        self.assertNotIn('р. року', html)
        self.assertIn('від 13.10.2026', html)                 # payment purpose
        self.assertIn('1%s500%s000,00' % (NBSP, NBSP), html)  # amount
        self.assertIn('1%s000' % NBSP, html)                  # quantity
        self.assertIn('вул. Тестова, 1, Київ', html)          # supplier address without legal address
        self.assertIn('вул. Покупця, 2', html)                # buyer address
        self.assertIn('ЄДРПОУ: %s' % BUYER_EDRPOU, html)
        self.assertIn('Директор', html)
        self.assertIn('Тестенко Т.Т.', html)
        self.assertNotIn('Сплатити до:', html)

    def test_validity_note(self):
        """Термін дії: дата з замовлення, інакше стандартний текст."""
        self.assertIn('Рахунок дійсний до 20.10.2026.',
                      self._render(self._order(validity_date=date(2026, 10, 20))))
        self.assertIn('Рахунок дійсний до оплати протягом 3 банківських днів.',
                      self._render(self._order(validity_date=False)))

    def test_terms_printed(self):
        """«Умови й положення» замовлення друкуються під підсумками."""
        html = self._render(self._order(note='<p>Курс НБУ на дату оплати (тест)</p>'))
        self.assertIn('Курс НБУ на дату оплати (тест)', html)

    def test_print_menu_only_in_uah(self):
        """У меню «Друк» звіт є лише для замовлень у гривні."""
        report = self.env.ref(REPORT)

        def is_available(order):
            return report.id in report.get_valid_action_reports('sale.order', order.ids)

        self.assertTrue(is_available(self._order()))
        self.assertFalse(is_available(self._order(pricelist=self.pricelist_usd)))
