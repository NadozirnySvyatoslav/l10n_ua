import base64
import logging

from odoo import models
from odoo.tools import file_open

_logger = logging.getLogger(__name__)


class Website(models.Model):
    _inherit = 'website'

    def _l10n_ua_apply_branding(self):
        """Проставляємо назву й логотип website (замість дефолтних
        "My Website" / "Your Logo"). Викликається з data-файлу на кожному
        оновленні модуля, бо website.default_website створений з noupdate=1
        і звичайний data-запис його не оновлює.
        """
        websites = self.search([])
        if not websites:
            return
        vals = {'name': 'many2one'}
        try:
            with file_open('l10n_ua_landing/static/src/img/logo.png', 'rb') as f:
                vals['logo'] = base64.b64encode(f.read()).decode()
        except OSError:
            _logger.warning('l10n_ua_landing: logo.png не знайдено, лишаємо дефолтний логотип')
        websites.write(vals)
