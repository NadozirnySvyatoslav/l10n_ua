import json

from odoo import http
from odoo.tests import HttpCase, tagged

from ..controllers.report import _sanitize_disposition


@tagged('post_install', '-at_install', 'l10n_ua_doc_reports')
class TestReportFilename(HttpCase):

    def test_sanitize_disposition(self):
        fixed = _sanitize_disposition("attachment; filename*=UTF-8''%D0%90%D0%BA%D1%82_INV%2F2026%2F00027.pdf")
        self.assertIn("%D0%90%D0%BA%D1%82_INV_2026_00027.pdf", fixed)
        self.assertIsNone(_sanitize_disposition("attachment; filename*=UTF-8''Act_S00012.pdf"))
        self.assertIsNone(_sanitize_disposition(None))

    def test_download_keeps_full_name(self):
        """Номер з «/» не має обрізати ім'я файлу до останнього сегмента."""
        view = self.env['ir.ui.view'].create({
            'name': 'test_report_filename',
            'type': 'qweb',
            'key': 'l10n_ua_doc_reports.test_report_filename',
            'arch': '<t t-name="l10n_ua_doc_reports.test_report_filename"><div>ok</div></t>',
        })
        self.env['ir.actions.report'].create({
            'name': 'Test act',
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': view.key,
            'print_report_name': "'Акт_%s' % object.name",
        })
        partner = self.env['res.partner'].create({'name': 'INV/2026/00027'})
        self.authenticate('admin', 'admin')
        response = self.url_open('/report/download', data={
            'data': json.dumps([f'/report/pdf/{view.key}/{partner.id}', 'qweb-pdf']),
            'csrf_token': http.Request.csrf_token(self),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("%D0%90%D0%BA%D1%82_INV_2026_00027.pdf", response.headers['Content-Disposition'])
