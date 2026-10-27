from odoo import models, _
from odoo.exceptions import UserError


class L10nUaSignMixin(models.AbstractModel):
    """Домішка для клієнтського КЕП-підпису документів моделі.

    Успадкуйте у своїй моделі й реалізуйте два методи:

    * ``kep_prepare_signing()`` — повертає, що саме підписати (документи +
      опційний ``auth_subject`` для заголовка Authorization);
    * ``kep_submit_signed(signed, auth_signature)`` — обробляє готові підписи
      (подача/збереження) і повертає результат (напр. квитанцію).

    Кнопка у формі викликає ``action_kep_sign()`` — вона відкриває універсальне
    OWL-вікно ``l10n_ua_sign.kep_sign`` поверх форми, де користувач обирає
    файл-ключ і пароль, а підпис рахується в браузері (IIT euscp). Приватний ключ
    і пароль на сервер не потрапляють; зчитаний ключ браузер пам'ятає у вкладці
    кілька хвилин, тож наступні дії (у будь-якому модулі) не просять пароль знову.
    Після закриття вікна форма, з якої його відкрили, перечитується.
    """
    _name = 'l10n_ua.sign.mixin'
    _description = 'КЕП Signing Mixin'

    def action_kep_sign(self, mode=None):
        """Відкрити вікно клієнтського КЕП-підпису для цього запису.

        :param mode: мітка сценарію, якщо модель має кілька дій із підписом
            (напр. ``'sign'`` / ``'submit'``). Вікно передає її обом викликам
            контракту в контексті як ``kep_mode``.
        """
        self.ensure_one()
        params = {'model': self._name, 'res_id': self.id}
        if mode:
            params['mode'] = mode
        return {
            'type': 'ir.actions.client',
            'tag': 'l10n_ua_sign.kep_sign',
            'name': _('Підпис КЕП'),
            'target': 'new',
            'params': params,
            # Кнопки — у самому вікні: їхній набір залежить від кроку.
            'context': {'dialog_size': 'medium', 'footer': False},
        }

    def kep_prepare_signing(self):
        """Дані для браузерного підпису (перевизначає споживач).

        Очікуваний формат повернення::

            {
              'auth_subject': <рядок для підпису заголовка Authorization|None>,
              'submit_label': <що робить дія, для кнопки: «Перевірити з'єднання»|None>,
              'description': <пояснення користувачу, навіщо підпис|None>,
              'close_action': <дія після успіху замість повернення до форми|None>,
              'documents': [
                 {'name': 'doc',
                  'data_b64': <base64 даних для підпису>,
                  'format': 'cades' | 'cades_detached' | 'envelope' | 'asic'
                            | 'dps_transport',
                  'filename': 'file.xml',
                  'recipient_cert_b64': <base64 cert отримувача, для 'envelope'>},
                 ...
              ],
            }

        ``cades_detached`` — відкріплений підпис (без даних усередині), як його
        приймають ЕДО-сервіси. ``data_b64`` — base64 сирих байтів, які підписуються (для XML це вміст
        файлу; браузер декодує перед підписом). ``documents`` може бути
        порожнім, якщо потрібен лише підпис ``auth_subject`` (авторизація) —
        тоді вікно робить усе однією кнопкою «Зчитати ключ і <submit_label>».
        Документи ж користувач бачить списком і підписує окремою кнопкою, вже
        звіривши власника ключа.
        """
        raise UserError(_(
            'Модель %s не реалізує kep_prepare_signing().') % self._name)

    def kep_submit_signed(self, signed, auth_signature=None):
        """Обробити готові підписи (перевизначає споживач).

        :param signed: dict ``{name: signature_base64}`` — по одному підпису на
            документ із ``documents`` (ключ = ``name``).
        :param auth_signature: base64-підпис ``auth_subject`` (для заголовка
            Authorization), якщо його запитували; інакше None.
        :return: довільний JSON-серіалізовний результат (напр.
            ``{'receipt': ...}``), який побачить діалог.
        """
        raise UserError(_(
            'Модель %s не реалізує kep_submit_signed().') % self._name)
