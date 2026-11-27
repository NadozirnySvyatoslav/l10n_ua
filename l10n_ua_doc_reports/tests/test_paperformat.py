"""Формати паперу: форми без шапки компанії й звіти з шапкою не ділять один формат."""
from odoo.tests import TransactionCase, tagged

FORM_REPORTS = (
    'l10n_ua_doc_reports.action_report_rahunok_invoice',
    'l10n_ua_doc_reports.action_report_rahunok_sale',
    'l10n_ua_doc_reports.action_report_act',
    'l10n_ua_doc_reports.action_report_vydatkova',
)


@tagged('post_install', '-at_install', 'l10n_ua_doc_reports')
class TestPaperformat(TransactionCase):

    def test_forms_use_form_paperformat(self):
        """Форми на web.basic_layout друкуються на форматі без місця під шапку."""
        form_format = self.env.ref('l10n_ua_doc_reports.paperformat_ua_form')
        self.assertEqual(form_format.margin_top, 10)
        self.assertEqual(form_format.header_spacing, 0)
        for xmlid in FORM_REPORTS:
            self.assertEqual(self.env.ref(xmlid).paperformat_id, form_format, xmlid)

    def test_report_paperformat_leaves_room_for_header(self):
        """Спільний формат для звітів з web.external_layout (бухгалтерія, ОЗ, ФОП,
        відрядження) лишає місце під шапку компанії, інакше вона накладається на текст."""
        report_format = self.env.ref('l10n_ua_doc_reports.paperformat_ua_report')
        self.assertEqual(report_format.margin_top, 30)
        self.assertEqual(report_format.header_spacing, 25)
        self.assertFalse(
            self.env['ir.actions.report'].search([
                ('paperformat_id', '=', report_format.id),
                ('report_name', 'in', [self.env.ref(x).report_name for x in FORM_REPORTS]),
            ]),
            'Forms without the company header must not use paperformat_ua_report',
        )
