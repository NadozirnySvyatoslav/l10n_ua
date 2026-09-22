"""Tests for tax invoices (податкові накладні) — Flow 6/7 from ACCOUNTING_UKRAINE.md.

Tests cover:
- Tax invoice creation (issued/received)
- Line totals computation
- Registration deadline calculation
- State workflow
- XML generation
"""

from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

_CONFIG = 'l10n_ua.tax.cabinet.config'
_CONFIG_PATH = ('odoo.addons.l10n_ua_tax_cabinet.models.'
                'l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig')


@tagged('post_install', '-at_install')
class TestTaxInvoice(TransactionCase):
    """Test tax invoices (податкові накладні)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Тестовий покупець',
        })
        # Enable VAT payer
        cls.company.write({
            'l10n_ua_is_vat_payer': True,
            'l10n_ua_vat_ipn': '123456789012',
        })

    def _create_tax_invoice(self, invoice_type='issued', **kwargs):
        """Helper to create a tax invoice with one line."""
        vals = {
            'doc_type': 'pn',
            'number': '1',
            'date': date(2025, 6, 10),
            'invoice_type': invoice_type,
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'line_ids': [(0, 0, {
                'name': 'Консультаційні послуги',
                'quantity': 1,
                'price_unit': 10000,
                'vat_rate': '20',
                'dkpp_code': '70.22.11-00.00',
            })],
        }
        vals.update(kwargs)
        return self.env['l10n_ua.tax.invoice'].create(vals)

    def test_tax_invoice_creation(self):
        """Tax invoice should be created in draft state."""
        ti = self._create_tax_invoice()
        self.assertEqual(ti.state, 'draft')
        self.assertTrue(ti.name)

    def test_tax_invoice_line_amounts(self):
        """Line amounts should compute base and VAT correctly."""
        ti = self._create_tax_invoice()
        line = ti.line_ids[0]
        self.assertEqual(line.base_amount, 10000)
        self.assertEqual(line.vat_amount, 2000)  # 10000 × 20%

    def test_tax_invoice_totals(self):
        """Invoice totals should sum line amounts."""
        ti = self._create_tax_invoice()
        self.assertEqual(ti.total_base, 10000)
        self.assertEqual(ti.total_vat, 2000)
        self.assertEqual(ti.total_amount, 12000)

    def test_tax_invoice_registration_deadline(self):
        """Registration deadline should be computed from date."""
        # Date 10th (1-15): deadline should be end of month or 5th next month (wartime)
        ti = self._create_tax_invoice(date=date(2025, 6, 10))
        self.assertTrue(ti.registration_deadline,
                        'Registration deadline should be computed')

    def test_tax_invoice_issued_state_workflow(self):
        """Issued invoice: draft → registered (через підписаний конверт) → cancelled.

        Реєстрація тепер — реальний релей у ЄРПН (#146): action_register_erpn
        лише відкриває браузерний підпис, а статус 'registered' виставляє
        erpn_submit_signed за квитанцією ДПС (тут API замокано).
        """
        # Конфіг кабінету (upsert через UNIQUE(company_id)).
        cfg = self.env[_CONFIG].with_context(active_test=False).search(
            [('company_id', '=', self.company.id)], limit=1)
        cfg_vals = {'name': 'Кабінет', 'taxpayer_code': '12345678', 'active': True}
        if cfg:
            cfg.write(cfg_vals)
        else:
            self.env[_CONFIG].create({**cfg_vals, 'company_id': self.company.id})

        ti = self._create_tax_invoice('issued')
        self.assertEqual(ti.state, 'draft')

        # Кнопка відкриває віджет підпису, статус ще не змінюється.
        action = ti.action_register_erpn()
        self.assertEqual(action['tag'], 'l10n_ua_sign.kep_sign')
        self.assertEqual(ti.state, 'draft')

        # Підписаний у браузері конверт подано → квитанція → registered.
        with patch(_CONFIG_PATH + '._api_submit_document_presigned',
                   return_value={'message': 'прийнято'}):
            ti.kep_submit_signed({'doc': 'ENV=='}, 'AUTH==')
        self.assertEqual(ti.state, 'registered')

        ti.action_cancel()
        self.assertEqual(ti.state, 'cancelled')

    def test_tax_invoice_received_state_workflow(self):
        """Received invoice: received_status tracks expected → received → erpn_verified."""
        ti = self._create_tax_invoice('received')
        self.assertEqual(ti.received_status, 'expected')
        ti.action_mark_received()
        self.assertEqual(ti.received_status, 'received')
        ti.action_mark_erpn_verified()
        self.assertEqual(ti.received_status, 'erpn_verified')

    def test_tax_invoice_cancel_and_draft(self):
        """Should be able to cancel and return to draft."""
        ti = self._create_tax_invoice()
        ti.action_cancel()
        self.assertEqual(ti.state, 'cancelled')
        ti.action_draft()
        self.assertEqual(ti.state, 'draft')

    def test_tax_invoice_multiple_rates(self):
        """Invoice with lines at different VAT rates."""
        ti = self.env['l10n_ua.tax.invoice'].create({
            'doc_type': 'pn',
            'number': '2',
            'date': date(2025, 6, 15),
            'invoice_type': 'issued',
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'name': 'Товар 20%', 'quantity': 1, 'price_unit': 10000,
                        'vat_rate': '20', 'uktzed_code': '8471300000'}),
                (0, 0, {'name': 'Ліки 7%', 'quantity': 1, 'price_unit': 5000,
                        'vat_rate': '7', 'uktzed_code': '3004900000'}),
                (0, 0, {'name': 'Експорт 0%', 'quantity': 1, 'price_unit': 8000,
                        'vat_rate': '0', 'uktzed_code': '9403208000'}),
            ],
        })
        self.assertEqual(ti.total_base, 23000)
        self.assertEqual(ti.total_vat, 2350)  # 2000 + 350 + 0

    def test_xml_generation(self):
        """XML generation should produce file content."""
        ti = self._create_tax_invoice()
        ti.action_generate_xml()
        self.assertTrue(ti.file_xml, 'XML file should be generated')
        self.assertTrue(ti.file_xml_name, 'XML filename should be set')
