"""Оновлення 19.0.1.5.0 (#701, ADR 0005): вид субконто без ir.model.

Поле `model_id` (Many2one на ir.model) замінено на Selection `model_name`.
Колонка `model_name` уже була (related store=True), тож дані не переносимо,
лише:

- дозаповнюємо `model_name` з `model_id` там, де вони розійшлися або порожні;
- звіряємо значення видів, створених користувачем, з базовим переліком і
  пишемо в лог попередження про моделі поза ним. Оновлення це не ламає: значення лишається в базі, вид
  субконто читається як і раніше, а виправити його треба вручну, якщо модель
  не додає мостовий модуль (через `_selection_subconto_models`).
"""

import logging

from odoo.addons.l10n_ua_account_base.models.l10n_ua_subconto import BASE_SUBCONTO_MODELS

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'l10n_ua_subconto_type' AND column_name = 'model_id'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE l10n_ua_subconto_type t
               SET model_name = m.model
              FROM ir_model m
             WHERE m.id = t.model_id
               AND t.model_name IS DISTINCT FROM m.model
        """)
        if cr.rowcount:
            _logger.info('#701: model_name дозаповнено з model_id для %s видів субконто',
                         cr.rowcount)

    # Види з даних встановленого модуля (мостового, напр. subconto_hr) не
    # звіряємо: їхню модель до переліку додає сам модуль.
    cr.execute("""
        SELECT t.id, t.code, t.model_name
          FROM l10n_ua_subconto_type t
         WHERE NOT EXISTS (
               SELECT 1 FROM ir_model_data d
                 JOIN ir_module_module mm ON mm.name = d.module AND mm.state IN ('installed', 'to upgrade')
                WHERE d.model = 'l10n_ua.subconto.type' AND d.res_id = t.id)
         ORDER BY t.id
    """)
    for type_id, code, model_name in cr.fetchall():
        if not model_name:
            _logger.warning(
                '#701: вид субконто id=%s (%s) без моделі; заповніть «Reference Model» вручну',
                type_id, code)
        elif model_name not in BASE_SUBCONTO_MODELS:
            _logger.warning(
                '#701: вид субконто id=%s (%s) посилається на %s поза базовим переліком; '
                'якщо цю модель не додає мостовий модуль (_selection_subconto_models), '
                'виправте вид вручну',
                type_id, code, model_name)
