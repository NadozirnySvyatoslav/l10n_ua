from datetime import timedelta

from odoo import fields, models


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    def _l10n_ua_convert(self, from_amount, to_currency, company, date,
                         round=True):  # noqa: A002 (core `_convert` spelling)
        """Конвертація за курсом, ДАТОВАНИМ саме ``date``.

        Odoo 20 змінило вибірку курсу: ``res.currency._get_rates`` шукає
        ``('name', '<', date)`` замість ``<=`` (Odoo 19). Тобто курс із
        датою 30.06 починає діяти лише з 01.07, а конвертація на 30.06
        бере попередній запис.

        Для України це неприпустимо: офіційний курс НБУ, встановлений на
        дату X, застосовується саме на дату X — і в переоцінці валютних
        залишків, і в розрахунку зарплати за валютним окладом. Тому
        звертаємось до ядра з наступним днем: вибірка ``name < date + 1``
        дає рівно той курс, що датований ``date``.

        Усюди, де сума прив'язана до конкретної дати документа, слід
        викликати цей метод, а не ``_convert`` напряму.
        """
        if date:
            date = fields.Date.to_date(date) + timedelta(days=1)
        return self._convert(from_amount, to_currency, company, date,
                             round=round)
