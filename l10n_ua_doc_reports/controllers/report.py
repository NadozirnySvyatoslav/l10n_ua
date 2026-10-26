from urllib.parse import unquote

from odoo.http import content_disposition, route
from odoo.addons.web.controllers.report import ReportController


def _sanitize_disposition(header):
    """Replace path separators in the attachment filename.

    Document numbers like ``INV/2026/00027`` end up in ``print_report_name``;
    browsers treat ``/`` as a directory separator and keep only ``00027.pdf``.
    """
    prefix = "filename*=UTF-8''"
    if not header or prefix not in header:
        return None
    filename = unquote(header.split(prefix, 1)[1].split(';', 1)[0])
    clean = filename.replace('/', '_').replace('\\', '_')
    if clean == filename:
        return None
    return content_disposition(clean)


class UaReportController(ReportController):

    @route()
    def report_download(self, data, context=None, token=None, readonly=True):
        response = super().report_download(data, context=context, token=token, readonly=readonly)
        if response is not None:
            fixed = _sanitize_disposition(response.headers.get('Content-Disposition'))
            if fixed:
                response.headers['Content-Disposition'] = fixed
        return response
