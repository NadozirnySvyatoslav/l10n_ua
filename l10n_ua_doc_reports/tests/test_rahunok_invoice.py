"""Рахунок-фактура з рахунку клієнта. Усі реквізити в тестах вигадані."""
from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

REPORT = 'l10n_ua_doc_reports.action_report_rahunok_invoice'
NBSP = '\u00a0'

# Fictitious requisites with valid checksums; bank MFO in the IBANs is 123456
SUPPLIER_EDRPOU = '11111116'
BUYER_EDRPOU = '22222221'
SUPPLIER_IPN = '1234567899'
IBAN_UAH = 'UA781234560000026001234567890'
IBAN_OTHER = 'UA831234560000026009876543210'


@tagged('post_install', '-at_install', 'l10n_ua_doc_reports')
class TestRahunokInvoice(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.setup_other_currency('UAH')
        cls.eur = cls.setup_other_currency('EUR')
        cls.company_partner = cls.env.company.partner_id
        cls.company_partner.write({
            'l10n_ua_legal_address': 'вул. Тестова, 1, 01001, Київ, Україна',
            'edrpou': SUPPLIER_EDRPOU,
            'l10n_ua_chief_name': 'Тестенко Т.Т.',
            'l10n_ua_chief_position': 'Директор',
        })
        cls.bank = cls.env['res.bank'].create({'name': 'АТ «Тестовий банк»', 'bic': 'TESTUAUX'})
        # The foreign-currency account comes first: the report must not just take bank_ids[:1]
        cls.account_eur = cls.env['res.partner.bank'].create({
            'acc_number': IBAN_OTHER,
            'partner_id': cls.company_partner.id,
            'bank_id': cls.bank.id,
            'currency_id': cls.eur.id,
            'sequence': 1,
        })
        cls.account_uah = cls.env['res.partner.bank'].create({
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
        cls.vat_20_included = cls.env['account.tax'].create({
            'name': 'ПДВ 20% у ціні (тест)', 'amount': 20.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include_override': 'tax_included',
            'company_id': cls.env.company.id,
        })

    def _invoice(self, move_type='out_invoice', post=True, lines=None, **vals):
        vals.setdefault('currency_id', self.uah.id)
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.customer.id,
            'invoice_date': '2026-10-11',
            'date': '2026-10-11',
            'invoice_line_ids': [(0, 0, line) for line in (lines or [{
                'name': 'Послуги з розробки',
                'quantity': 10,
                'price_unit': 1500,
                'tax_ids': [(6, 0, [])],
            }])],
            **vals,
        })
        if post:
            move.action_post()
        return move

    def _render(self, invoice, report=REPORT):
        return self.env['ir.actions.report']._render_qweb_html(report, invoice.ids)[0].decode()

    # Bank account and MFO

    def test_bank_account_from_invoice(self):
        """Друкується рахунок, обраний у документі, а не перший рахунок компанії."""
        invoice = self._invoice(partner_bank_id=self.account_uah.id)
        self.assertEqual(invoice._get_ua_bank_account(), self.account_uah)

    def test_bank_account_fallback_by_currency(self):
        """Без рахунку в документі — рахунок компанії у валюті документа."""
        invoice = self._invoice()
        invoice.partner_bank_id = False
        self.assertEqual(invoice._get_ua_bank_account(), self.account_uah)

    def test_bank_account_without_currency_is_company_currency(self):
        """Рахунок без валюти вважається рахунком у валюті компанії."""
        no_currency = self.env['res.partner.bank'].create({
            'acc_number': 'UA911234560000026005555555555',
            'partner_id': self.company_partner.id,
            'sequence': 3,
        })
        invoice = self._invoice(currency_id=self.env.company.currency_id.id)
        invoice.partner_bank_id = False
        self.assertEqual(invoice._get_ua_bank_account(), no_currency)

    def test_mfo_from_iban_not_bic(self):
        """МФО — з IBAN (позиції 5–10), а не SWIFT з поля bic."""
        if 'ua_mfo' in self.bank._fields:
            self.bank.ua_mfo = False
        invoice = self._invoice()
        self.assertEqual(invoice._get_ua_bank_mfo(self.account_uah), '123456')
        self.assertEqual(invoice._get_ua_bank_line(self.account_uah),
                         'в банку АТ «Тестовий банк», МФО 123456')
        foreign = self.env['res.partner.bank'].create({
            'acc_number': 'DE89370400440532013000',
            'partner_id': self.company_partner.id,
        })
        self.assertEqual(invoice._get_ua_bank_mfo(foreign), '')

    def test_mfo_from_bank_field(self):
        """Якщо в банку заповнено ua_mfo (l10n_ua_bank_sync), береться воно."""
        if 'ua_mfo' not in self.bank._fields:
            self.skipTest('l10n_ua_bank_sync is not installed')
        self.bank.ua_mfo = '654321'
        invoice = self._invoice()
        self.assertEqual(invoice._get_ua_bank_mfo(self.account_uah), '654321')

    # Partner requisites

    def test_partner_address_fallback(self):
        """Без юридичної адреси друкується звичайна адреса партнера."""
        invoice = self._invoice()
        address = invoice._get_ua_partner_address(self.customer)
        self.assertTrue(address.startswith('вул. Покупця, 2, Львів, '), address)
        self.assertEqual(invoice._get_ua_partner_address(self.company_partner),
                         'вул. Тестова, 1, 01001, Київ, Україна')

    def test_partner_codes(self):
        self.company_partner.write({'ipn': SUPPLIER_IPN, 'is_vat_payer': True})
        invoice = self._invoice()
        self.assertEqual(
            invoice._get_ua_partner_codes(self.company_partner, show_vat_payer=True),
            'ЄДРПОУ: %s, ІПН: %s, платник ПДВ' % (SUPPLIER_EDRPOU, SUPPLIER_IPN))
        self.assertEqual(invoice._get_ua_partner_codes(self.customer),
                         'ЄДРПОУ: %s' % BUYER_EDRPOU)

    # Lines and amounts

    def test_report_lines_only_products(self):
        """Розділи, підрозділи й нотатки не друкуються як позиції."""
        invoice = self._invoice(lines=[
            {'display_type': 'line_section', 'name': 'Розділ'},
            {'display_type': 'line_subsection', 'name': 'Підрозділ'},
            {'name': 'Послуга', 'quantity': 1, 'price_unit': 100, 'tax_ids': [(6, 0, [])]},
            {'display_type': 'line_note', 'name': 'Примітка'},
        ])
        self.assertEqual(invoice._get_ua_report_lines().mapped('name'), ['Послуга'])

    def test_price_unit_without_vat_for_tax_included(self):
        """Ціна без ПДВ для податку «у ціні»: кількість × ціна = сума без ПДВ."""
        invoice = self._invoice(lines=[{
            'name': 'Послуга з ПДВ у ціні',
            'quantity': 3,
            'price_unit': 1200,
            'tax_ids': [(6, 0, self.vat_20_included.ids)],
        }])
        line = invoice._get_ua_report_lines()
        self.assertAlmostEqual(invoice._get_ua_line_price_unit_excl(line), 1000.0)
        self.assertAlmostEqual(line.price_subtotal, 3000.0)
        self.assertAlmostEqual(line.price_total, 3600.0)
        html = self._render(invoice)
        self.assertIn('Ціна без ПДВ, грн', html)
        self.assertIn('1%s000,00' % NBSP, html)   # unit price without VAT
        self.assertIn('3%s600,00' % NBSP, html)   # amount with VAT

    def test_price_unit_without_vat_keeps_price_precision(self):
        """Точність «Product Price» 4 знаки: ціна без ПДВ не обрізається до копійок (#365)."""
        self.env.ref('product.decimal_price').digits = 4
        invoice = self._invoice(lines=[{
            'name': 'Товар з ПДВ у ціні',
            'quantity': 10,
            'price_unit': 10.1234,
            'tax_ids': [(6, 0, self.vat_20_included.ids)],
        }])
        line = invoice._get_ua_report_lines()
        self.assertAlmostEqual(invoice._get_ua_line_price_unit_excl(line), 8.4362, places=4)
        self.assertIn('8,4362', self._render(invoice))

    def test_number_formats(self):
        Move = self.env['account.move']
        self.assertEqual(Move._ua_format_number(146150), '146%s150,00' % NBSP)
        self.assertEqual(Move._ua_format_number(1234567.5), '1%s234%s567,50' % (NBSP, NBSP))
        self.assertEqual(Move._ua_format_quantity(79.0), '79')
        self.assertEqual(Move._ua_format_quantity(79.75), '79,75')
        self.assertEqual(Move._ua_format_quantity(1000), '1%s000' % NBSP)
        self.assertEqual(Move._ua_format_price(1850), '1%s850,00' % NBSP)

    # Dates

    def test_date_format(self):
        """Дата з українськими лапками і без дубля «року»."""
        invoice = self._invoice()
        self.assertEqual(invoice._get_ua_date_formatted(date(2026, 10, 11)), '«11» жовтня 2026 р.')
        self.assertEqual(invoice._get_ua_date_short(date(2026, 10, 26)), '26.10.2026')
        self.assertEqual(invoice._get_ua_date_short(False), '')

    def test_draft_date_in_payment_purpose(self):
        """Чернетка без дати рахунку: і заголовок, і «призначення платежу» беруть дату проведення."""
        draft = self._invoice(post=False, invoice_date=False, date='2026-10-05')
        html = self._render(draft)
        self.assertIn('від «05» жовтня 2026 р.', html)
        self.assertIn('від 05.10.2026', html)

    # Print menu and side effects

    def test_print_menu_only_customer_invoices_in_uah(self):
        """У меню «Друк» звіт є лише для рахунків клієнтам у гривні."""
        report = self.env.ref(REPORT)

        def is_available(move):
            return report.id in report.get_valid_action_reports('account.move', move.ids)

        self.assertTrue(is_available(self._invoice()))
        self.assertFalse(is_available(self._invoice(currency_id=self.eur.id)))
        self.assertFalse(is_available(self._invoice(move_type='out_refund')))
        self.assertFalse(is_available(self._invoice(move_type='in_invoice')))

    def test_standard_invoice_not_restyled(self):
        """Модуль не змінює стандартний звіт рахунку Odoo."""
        self.assertFalse(self.env.ref('l10n_ua_doc_reports.report_invoice_document_ua_style',
                                      raise_if_not_found=False))

    # Rendering

    def test_render(self):
        invoice = self._invoice(partner_bank_id=self.account_uah.id)
        html = self._render(invoice)
        self.assertIn('Рахунок-фактура № %s' % invoice.name, html)
        self.assertIn('від «11» жовтня 2026 р.', html)
        self.assertNotIn('р. року', html)
        self.assertIn(IBAN_UAH, html)
        self.assertNotIn(IBAN_OTHER, html)
        self.assertIn('МФО 123456', html)
        self.assertNotIn('TESTUAUX', html)
        self.assertIn('вул. Покупця, 2', html)
        self.assertIn('15%s000,00' % NBSP, html)
        self.assertIn('Сума з ПДВ, грн', html)
        self.assertIn('Сплатити до:', html)
        self.assertIn('Директор', html)
        self.assertIn('Тестенко Т.Т.', html)

    def test_narration_printed(self):
        invoice = self._invoice(narration='<p>Розрахунок суми за курсом (тест)</p>')
        self.assertIn('Розрахунок суми за курсом (тест)', self._render(invoice))

    def test_render_act_and_vydatkova_date(self):
        """Акт і видаткова накладна: дата без дубля «року»."""
        invoice = self._invoice()
        for report in ('l10n_ua_doc_reports.action_report_act',
                       'l10n_ua_doc_reports.action_report_vydatkova'):
            html = self._render(invoice, report)
            self.assertIn('«11» жовтня 2026 р.', html, report)
            self.assertNotIn('р. року', html, report)
