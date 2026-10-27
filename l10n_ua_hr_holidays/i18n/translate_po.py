#!/usr/bin/env python3
"""Translate PO file for l10n_ua_hr_base module."""

import re

TRANSLATIONS = {
    # Common fields from mail.thread, mail.activity.mixin
    "Action Needed": "Потрібна дія",
    "Activities": "Активності",
    "Activity Exception Decoration": "Оформлення виключення активності",
    "Activity State": "Стан активності",
    "Activity Type Icon": "Іконка типу активності",
    "Approve": "Затвердити",
    "Approved": "Затверджено",
    "Attachment Count": "Кількість вкладень",
    "Cancel": "Скасувати",
    "Confirm": "Підтвердити",
    "Created by": "Створив",
    "Created on": "Створено",
    "Department": "Підрозділ",
    "Followers": "Підписники",
    "Followers (Partners)": "Підписники (Партнери)",
    "Font awesome icon e.g. fa-tasks": "Іконка Font Awesome, напр. fa-tasks",
    "Has Message": "Є повідомлення",
    "ID": "ID",
    "Icon": "Іконка",
    "Icon to indicate an exception activity.": "Іконка для позначення виключної активності.",
    "If checked, new messages require your attention.": "Якщо позначено, нові повідомлення потребують вашої уваги.",
    "If checked, some messages have a delivery error.": "Якщо позначено, деякі повідомлення мають помилку доставки.",
    "Is Follower": "Є підписником",
    "Last Updated by": "Оновив",
    "Last Updated on": "Оновлено",
    "Message Delivery error": "Помилка доставки повідомлення",
    "Messages": "Повідомлення",
    "My Activity Deadline": "Термін моєї активності",
    "Name": "Назва",
    "Next Activity Calendar Event": "Подія календаря наступної активності",
    "Next Activity Deadline": "Термін наступної активності",
    "Next Activity Summary": "Опис наступної активності",
    "Next Activity Type": "Тип наступної активності",
    "Number of Actions": "Кількість дій",
    "Number of errors": "Кількість помилок",
    "Number of messages requiring action": "Кількість повідомлень, що потребують дії",
    "Number of messages with delivery error": "Кількість повідомлень з помилкою доставки",
    "Responsible User": "Відповідальний",
    "SMS Delivery error": "Помилка доставки SMS",
    "Set to Draft": "Повернути в чернетку",
    "Type of the exception activity on record.": "Тип виключної активності в записі.",
    "Vacation schedules must be approved before December 5th for the next year.": "Графіки відпусток мають бути затверджені до 5 грудня на наступний рік.",
    "Website Messages": "Повідомлення веб-сайту",
    "Website communication history": "Історія комунікації веб-сайту",
    
    # l10n_ua_hr_holidays translations
    "50%, 60%, 70% or 100% based on experience": "50%, 60%, 70% або 100% залежно від стажу",
    "Actual Days": "Фактичні дні",
    "Annual Additional Leave": "Щорічна додаткова відпустка",
    "Annual Basic Leave": "Щорічна основна відпустка",
    "Approval Date": "Дата затвердження",
    "Approved By": "Затверджено",
    "Average Daily Salary": "Середньоденна заробітна плата",
    "Balance After": "Залишок після",
    "Balance Before": "Залишок до",
    "Balance for this employee, leave type and year already exists!": "Залишок для цього працівника, типу відпустки та року вже існує!",
    "Calculate": "Розрахувати",
    "Calculate Compensation": "Розрахувати компенсацію",
    "Calendar Days": "Календарні дні",
    "Can unused days be transferred to next year": "Чи можна переносити невикористані дні на наступний рік",
    "Carried Over": "Перенесено",
    "Child Care": "Догляд за дитиною",
    "Childcare Leave": "Відпустка для догляду за дитиною",
    "Companies": "Компанії",
    "Create a vacation schedule for the year": "Створіть графік відпусток на рік",
    "Creative Leave": "Творча відпустка",
    "Days carried from previous year": "Днів перенесено з минулого року",
    "Days entitled for the year": "Належить днів за рік",
    "Days per Year": "Днів на рік",
    "Diagnosis Code (ICD-10)": "Код діагнозу (МКХ-10)",
    "Educational Leave": "Навчальна відпустка",
    "Electronic (e-TVN)": "Електронний (е-ТВН)",
    "Electronic sick leave ID from PFU system": "ID електронного лікарняного з системи ПФУ",
    "Employer": "Роботодавець",
    "Employer Amount": "Сума роботодавця",
    "Employer Days": "Дні роботодавця",
    "Entitled Days": "Належить днів",
    "e-TVN ID": "ID е-ТВН",
    "First 5 days paid by employer": "Перші 5 днів оплачує роботодавець",
    "PFU Amount": "Сума ПФУ",
    "PFU Days": "Дні ПФУ",
    "Generate Lines": "Згенерувати рядки",
    "If checked, vacation is counted in calendar days": "Якщо позначено, відпустка рахується в календарних днях",
    "Illness": "Захворювання",
    "Import UA Leave Types": "Імпорт типів відпусток UA",
    "Indicates if Ukrainian leave types have been imported for this company": "Вказує, чи імпортовано українські типи відпусток для цієї компанії",
    "Injury": "Травма",
    "Insurance experience for payment calculation": "Страховий стаж для розрахунку оплати",
    "Insurance Experience (years)": "Страховий стаж (роки)",
    "Leave Type": "Тип відпустки",
    "Mark as Paid": "Позначити як оплачено",
    "Maternity Leave": "Відпустка по вагітності та пологах",
    "Maximum days that can be transferred": "Максимум днів для перенесення",
    "Max Transfer Days": "Макс. днів для перенесення",
    "Min Continuous Days": "Мін. неперервних днів",
    "Min Experience (months)": "Мін. стаж (місяців)",
    "Minimum continuous vacation days (14 for annual)": "Мінімальна неперервна частина відпустки (14 для щорічної)",
    "No vacation balances found": "Залишків відпусток не знайдено",
    "Number of vacation days per year (24 is standard)": "Кількість днів відпустки на рік (24 - стандарт)",
    "Paid": "Оплачено",
    "Paid Leave": "Оплачувана відпустка",
    "Payment Calculation": "Розрахунок оплати",
    "Payment Percent": "Відсоток оплати",
    "Payment Source": "Джерело оплати",
    "Period 1 Days": "Період 1 днів",
    "Period 1 End": "Період 1 кінець",
    "Period 1 Start": "Період 1 початок",
    "Period 2 Days": "Період 2 днів",
    "Period 2 End": "Період 2 кінець",
    "Period 2 Start": "Період 2 початок",
    "Period 3 Days": "Період 3 днів",
    "Period 3 End": "Період 3 кінець",
    "Period 3 Start": "Період 3 початок",
    "Planned Days": "Заплановано днів",
    "Pregnancy and Childbirth": "Вагітність та пологи",
    "Prosthetics": "Протезування",
    "Quarantine": "Карантин",
    "Reference": "Номер",
    "Register a sick leave": "Зареєструвати лікарняний",
    "Re-import UA Leave Types": "Повторний імпорт типів відпусток UA",
    "Related Leave": "Пов'язана відпустка",
    "Remaining Days": "Залишок днів",
    "Requires 6 months of work experience": "Потребує 6 місяців стажу роботи",
    "Requires Work Experience": "Потребує стажу роботи",
    "Sanatorium Treatment": "Санаторне лікування",
    "Schedule": "Графік",
    "Schedule Lines": "Рядки графіка",
    "Sick Leave": "Лікарняний",
    "Sick Leave Document": "Документ лікарняного",
    "Sick Leave Number": "Номер лікарняного",
    "Sick Leaves": "Лікарняні",
    "Social Insurance Fund": "Фонд соціального страхування",
    "Social Leave": "Соціальна відпустка",
    "This will create any missing UA leave types. Continue?": "Це створить відсутні українські типи відпусток. Продовжити?",
    "Time Off": "Відпустка",
    "Time Off Type": "Тип відпустки",
    "Total": "Всього",
    "Total Amount": "Загальна сума",
    "Total Available": "Всього доступно",
    "Total Planned": "Всього заплановано",
    "Transferable": "Переноситься",
    "Type": "Тип",
    "UA Leave Category": "Категорія відпустки (UA)",
    "UA Leave Types Imported": "Типи відпусток UA імпортовано",
    "Ukrainian Settings": "Українські налаштування",
    "Ukrainian Specifics": "Українська специфіка",
    "Unpaid Leave": "Відпустка без збереження зарплати",
    "Used Days": "Використано днів",
    "Vacation Balance": "Залишок відпустки",
    "Vacation Work-Year Anchor": "Анкер робочого року відпустки",
    "Date the annual (work-year) vacation seniority is counted from, when it "
    "differs from the hire date. Set by the inter-company transfer wizard in "
    "\"Keep Work Year\" mode: art. 9 §3 of the Vacation Law lets the previous "
    "employer's seniority continue when the compensation for unused days is "
    "transferred along with the employee. Empty — the work year runs from the "
    "hire date.":
        "Дата, від якої рахується стаж для щорічної відпустки, якщо вона "
        "відрізняється від дати прийняття. Заповнює майстер переведення в "
        "режимі «Зберегти робочий рік»: ч. 3 ст. 9 Закону «Про відпустки» "
        "дозволяє зарахувати стаж попереднього роботодавця, якщо разом із "
        "працівником перераховано компенсацію за невикористані дні. Порожнє — "
        "робочий рік рахується від дати прийняття.",
    "Vacation balance before this leave": "Залишок відпустки до цієї відпустки",
    "Vacation Balances": "Залишки відпусток",
    "Vacation Order": "Наказ на відпустку",
    "Vacation Pay Amount": "Сума відпускних",
    "Vacation Schedule": "Графік відпусток",
    "Vacation schedule for this year and company already exists!": "Графік відпусток для цього року та компанії вже існує!",
    "Vacation Schedule Line": "Рядок графіка відпусток",
    "Vacation Schedules": "Графіки відпусток",
    "Vacation Year": "Рік відпустки",
    "Working Days": "Робочі дні",
    "Year": "Рік",
    "Year for which vacation is taken": "Рік, за який береться відпустка",
    "%d leave types have been created for %s": "%d типів відпусток створено для %s",
}


def is_english(text):
    """Check if text is primarily English (ASCII letters)."""
    if not text:
        return False
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters == 0:
        return False
    return ascii_letters / total_letters > 0.8


def translate_po(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    result = []
    i = 0
    translated_count = 0
    untranslated = []

    while i < len(lines):
        line = lines[i]
        result.append(line)

        # Handle msgid (both single-line and multi-line)
        if line.startswith('msgid "'):
            if line == 'msgid ""':
                # Multi-line msgid starting with empty string
                msgid = ""
                j = i + 1
                while j < len(lines) and lines[j].startswith('"'):
                    msgid += lines[j][1:-1]
                    result.append(lines[j])
                    j += 1
            else:
                # Single-line or continuation msgid
                msgid = line[7:-1]
                j = i + 1
                while j < len(lines) and lines[j].startswith('"'):
                    msgid += lines[j][1:-1]
                    result.append(lines[j])
                    j += 1

            # Check if msgstr is empty and we have a translation
            if j < len(lines) and lines[j].startswith('msgstr "'):
                msgstr_line = lines[j]
                # Check if msgstr is empty (either 'msgstr ""' alone or followed by empty continuations)
                if msgstr_line == 'msgstr ""':
                    # Check if next lines are empty string continuations
                    k = j + 1
                    msgstr_empty = True
                    while k < len(lines) and lines[k].startswith('"'):
                        if lines[k] != '""':
                            msgstr_empty = False
                            break
                        k += 1

                    if msgstr_empty and msgid and msgid in TRANSLATIONS:
                        translation = TRANSLATIONS[msgid]
                        # Handle multi-line translations
                        if '\n' in translation:
                            result.append('msgstr ""')
                            for part in translation.split('\n'):
                                result.append(f'"{part}\\n"')
                            # Remove trailing \n from last part
                            if result[-1].endswith('\\n"'):
                                result[-1] = result[-1][:-3] + '"'
                        else:
                            result.append(f'msgstr "{translation}"')
                        translated_count += 1
                        i = k
                        continue
                    elif msgstr_empty and msgid and is_english(msgid) and msgid not in TRANSLATIONS:
                        untranslated.append(msgid)

            # The msgid continuation lines were already copied above. Resume at
            # the msgstr line so the outer loop does not copy them a second
            # time — doing so duplicated them on every run and produced msgids
            # that no source string can ever match.
            i = j
            continue

        i += 1

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(result))

    print(f"Translated {translated_count} strings")

    if untranslated:
        print(f"\nUntranslated English strings ({len(untranslated)}):")
        for s in sorted(set(untranslated)):
            print(f'    "{repr(s)[1:-1]}": "",')


if __name__ == '__main__':
    translate_po('uk_UA.po', 'uk_UA.po')
