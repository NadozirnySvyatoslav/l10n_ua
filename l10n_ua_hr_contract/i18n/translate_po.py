#!/usr/bin/env python3
"""Translate PO file for l10n_ua_hr_contract module."""

TRANSLATIONS = {
    # Contract Types
    "Permanent (Indefinite)": "Безстроковий",
    "Fixed Term": "Строковий",
    "Seasonal Work": "Сезонна робота",
    "Temporary Work": "Тимчасова робота",
    "Civil Law Contract": "Цивільно-правовий договір",
    "Gig Contract (Diia.City)": "Гіг-контракт (Дія.Сіті)",
    "Author Contract": "Авторський договір",
    "Employment Contract (Ukraine)": "Трудовий договір (Україна)",

    # Work Modes
    "Full-time": "Повна зайнятість",
    "Part-time": "Часткова зайнятість",
    "Part-time Work": "Робота на неповний день",
    "Part-time Type": "Тип часткової зайнятості",
    "Remote Work": "Дистанційна робота",
    "Hybrid": "Гібридна робота",
    "Flexible Schedule": "Гнучкий графік",
    "Shift Work": "Змінна робота",
    "Reduced Working Hours": "Скорочений робочий час",
    "Internal Part-time": "Внутрішнє сумісництво",
    "External Part-time": "Зовнішнє сумісництво",

    # Work Conditions
    "Work Conditions": "Умови праці",
    "Work Conditions Change": "Зміна умов праці",
    "Normal": "Нормальні",
    "Hazardous (Шкідливі)": "Шкідливі",
    "Hazardous Conditions": "Шкідливі умови",
    "Heavy (Важкі)": "Важкі",
    "Underground Work": "Підземні роботи",
    "Night Work": "Нічна робота",
    "Special Conditions": "Особливі умови",
    "Hazard Class (1-4)": "Клас шкідливості (1-4)",
    "Hazard Subclass": "Підклас шкідливості",
    "Hazardous classification class according to DSTU": "Клас шкідливості згідно з ДСТУ",
    "Hazard subclass within the class": "Підклас шкідливості в межах класу",

    # Contract Fields
    "Contract": "Договір",
    "Contracts": "Договори",
    "Contract Details": "Деталі договору",
    "Contract Reference": "Посилання на договір",
    "Contract Type": "Тип договору",
    "Contract Extension": "Продовження договору",
    "UA Contracts": "Договори UA",
    "UA Contracts Count": "Кількість договорів UA",
    "Current UA Contract": "Поточний договір UA",
    "Current running Ukrainian contract": "Поточний діючий український договір",
    "Main Contract": "Основний договір",
    "Main Workplace": "Основне місце роботи",

    # Dates
    "Start Date": "Дата початку",
    "End Date": "Дата закінчення",
    "Effective Date": "Дата набуття чинності",
    "Date From": "Дата з",
    "Date To": "Дата до",
    "Date": "Дата",

    # Salary & Wages
    "Salary": "Заробітна плата",
    "Wage": "Оклад",
    "Total Wage": "Загальний оклад",
    "New Salary": "Новий оклад",
    "Previous Salary": "Попередній оклад",
    "Monthly gross salary": "Місячна заробітна плата (брутто)",
    "Salary Change": "Зміна окладу",
    "Salary Changes": "Зміни окладу",
    "Salary History": "Історія зарплати",
    "Record a salary change": "Зафіксувати зміну окладу",
    "Track salary changes for contracts with order references.": "Відстеження змін окладу за договорами з посиланнями на накази.",
    "Change Amount": "Сума зміни",
    "Change %": "Зміна %",
    "ESV Base": "База ЄСВ",

    # Allowances
    "Allowance Name": "Назва надбавки",
    "Allowances": "Надбавки",
    "Allowance Type": "Тип надбавки",
    "Allowance Types": "Типи надбавок",
    "Allowance type code must be unique!": "Код типу надбавки повинен бути унікальним!",
    "Contract Allowance": "Надбавка за договором",
    "Contract Allowances": "Надбавки за договором",
    "Total Allowances": "Всього надбавок",
    "Personal Allowance": "Персональна надбавка",
    "Create your first allowance type": "Створіть перший тип надбавки",
    "Related Allowance": "Пов'язана надбавка",
    "Automatically created allowance for this job combining": "Автоматично створена надбавка для цього суміщення",

    # Surcharges
    "Surcharge": "Доплата",
    "Surcharge %": "Доплата %",
    "Surcharge Amount": "Сума доплати",
    "Surcharge Type": "Тип доплати",
    "Calculated Surcharge": "Розрахована доплата",
    "Fixed surcharge amount": "Фіксована сума доплати",
    "Percentage of main salary as surcharge": "Відсоток від основного окладу як доплата",

    # Calculation
    "Calculation Method": "Метод розрахунку",
    "Calculated Amount": "Розрахована сума",
    "Amount": "Сума",
    "Percent": "Відсоток",
    "Fixed Amount": "Фіксована сума",
    "Fixed amount if calculation method is fixed": "Фіксована сума, якщо метод розрахунку - фіксований",
    "Percentage if calculation method is percent": "Відсоток, якщо метод розрахунку - відсотковий",
    "Percent of Salary": "Відсоток від окладу",
    "Percent of Minimum Wage": "Відсоток від мінімальної зарплати",
    "Default Percent": "Відсоток за замовчуванням",
    "Default Amount": "Сума за замовчуванням",

    # Work Schedule
    "Work Schedule": "Графік роботи",
    "Work Schedules": "Графіки роботи",
    "Work Schedule Line": "Рядок графіка роботи",
    "Schedule": "Графік",
    "Schedule Lines": "Рядки графіка",
    "Schedule Name": "Назва графіка",
    "Schedule Type": "Тип графіка",
    "Schedule Change": "Зміна графіка",
    "Standard (5-day week)": "Стандартний (5-денний тиждень)",
    "6-денний робочий тиждень": "6-денний робочий тиждень",
    "Summarized Accounting": "Підсумований облік",
    "Create your first work schedule": "Створіть перший графік роботи",

    # Working Time
    "Working Time": "Робочий час",
    "Working Hours": "Робочі години",
    "Working Hours Calendar": "Календар робочих годин",
    "Hours per Day": "Годин на день",
    "Hours per Week": "Годин на тиждень",
    "Working Days per Week": "Робочих днів на тиждень",
    "Working Day": "Робочий день",
    "Work From": "Робота з",
    "Work To": "Робота до",
    "Break From": "Перерва з",
    "Break To": "Перерва до",
    "Night Start Hour": "Початок нічного часу",
    "Night End Hour": "Кінець нічного часу",
    "Includes Night Work": "Включає нічну роботу",
    "Work Rate": "Ставка",
    "1.0 = full rate, 0.5 = half rate, etc.": "1.0 = повна ставка, 0.5 = половина ставки тощо",
    "Link to Odoo resource calendar for employee scheduling integration": "Посилання на календар ресурсів Odoo для інтеграції планування працівників",

    # Days of Week
    "Day of Week": "День тижня",
    "Monday": "Понеділок",
    "Tuesday": "Вівторок",
    "Wednesday": "Середа",
    "Thursday": "Четвер",
    "Friday": "П'ятниця",
    "Saturday": "Субота",
    "Sunday": "Неділя",

    # Probation
    "Probation": "Випробувальний термін",
    "Probation Period (days)": "Випробувальний термін (дні)",
    "Probation End Date": "Дата закінчення випробування",

    # Job Combining
    "Job Combining": "Суміщення посад",
    "Record job combining for employees": "Оформлення суміщення посад для працівників",
    "Combined Position": "Суміщувана посада",
    "Combined Department": "Суміщуваний підрозділ",

    # Amendments
    "Amendment": "Додаткова угода",
    "Amendments": "Додаткові угоди",
    "Amendment Date": "Дата додаткової угоди",
    "Amendment Number": "Номер додаткової угоди",
    "Amendment Type": "Тип зміни",
    "Contract Amendment": "Додаткова угода до договору",
    "Contract Amendments": "Додаткові угоди до договорів",
    "Record a contract amendment": "Оформити додаткову угоду",
    "Track all changes made to employment contracts.": "Відстеження всіх змін до трудових договорів.",
    "New Values": "Нові значення",
    "Previous Values": "Попередні значення",
    "New field values after amendment": "Нові значення полів після зміни",
    "Previous field values before amendment": "Попередні значення полів до зміни",
    "Position Change": "Зміна посади",
    "Work Intensity": "Інтенсивність роботи",
    "Detailed description of changes made": "Детальний опис внесених змін",
    "Changes": "Зміни",

    # Termination
    "Termination": "Звільнення",
    "Termination Date": "Дата звільнення",
    "Termination Reason": "Причина звільнення",
    "Termination Reasons": "Причини звільнення",
    "Termination reason code must be unique!": "Код причини звільнення повинен бути унікальним!",
    "Termination Order Number": "Номер наказу про звільнення",
    "Termination Order Date": "Дата наказу про звільнення",
    "Create your first termination reason": "Створіть першу причину звільнення",
    "Termination reasons are based on Ukrainian Labor Code articles.": "Причини звільнення базуються на статтях Кодексу законів про працю України.",
    "Labor Code Article": "Стаття КЗпП",
    "Paragraph": "Пункт",
    "e.g., п. 1, п. 2": "напр., п. 1, п. 2",
    "e.g., 36, 38, 40": "напр., 36, 38, 40",
    "Notice Days": "Днів попередження",
    "Days of advance notice required": "Необхідна кількість днів попередження",
    "Severance Pay Required": "Потрібна вихідна допомога",
    "Whether severance pay is required by law": "Чи потрібна вихідна допомога за законом",

    # Termination Reasons (Labor Code)
    "Own Will (Art. 38)": "За власним бажанням (ст. 38)",
    "By Agreement (Art. 36 p.1)": "За угодою сторін (ст. 36 п.1)",
    "Fixed Term Expiry (Art. 36 p.2)": "Закінчення строку (ст. 36 п.2)",
    "Transfer (Art. 36 p.5)": "Переведення (ст. 36 п.5)",
    "Employer Initiative (Art. 40)": "З ініціативи роботодавця (ст. 40)",
    "Beyond Control (Art. 36 p.3,4,6,7,8)": "Незалежні обставини (ст. 36 п.3,4,6,7,8)",

    # Severance Pay
    "Compensation": "Компенсація",
    "Compensation Amount": "Сума компенсації",
    "One Month Salary": "Місячний оклад",
    "Two Months Salary": "Двомісячний оклад",
    "Three Months Salary": "Тримісячний оклад",

    # Orders
    "Order Number": "Номер наказу",
    "Order Date": "Дата наказу",
    "Order Reference": "Посилання на наказ",
    "Order References": "Посилання на накази",
    "Orders": "Накази",
    "Hire Order Number": "Номер наказу про прийняття",
    "Hire Order Date": "Дата наказу про прийняття",
    "Cancellation Order": "Наказ про скасування",
    "Cancellation Order Date": "Дата наказу про скасування",
    "Full Text for Order": "Повний текст для наказу",

    # Status & States
    "Status": "Статус",
    "State": "Стан",
    "Draft": "Чернетка",
    "Running": "Діючий",
    "Expired": "Завершений",
    "Cancelled": "Скасовано",
    "Active": "Активний",
    "Archived": "Архівовано",
    "Applied": "Застосовано",
    "Confirmed": "Підтверджено",

    # Actions
    "Activate": "Активувати",
    "Apply": "Застосувати",
    "Cancel": "Скасувати",
    "Close": "Закрити",
    "Confirm": "Підтвердити",
    "Reset to Draft": "Повернути в чернетку",
    "Set to Draft": "Повернути в чернетку",

    # Common Fields
    "Name": "Назва",
    "Code": "Код",
    "Description": "Опис",
    "Notes": "Примітки",
    "Additional notes...": "Додаткові примітки...",
    "Sequence": "Послідовність",
    "Reference": "Посилання",
    "Full Reference": "Повне посилання",
    "Type": "Тип",
    "Category": "Категорія",
    "Period": "Період",
    "Total": "Всього",
    "Reason": "Причина",
    "Reason for Change": "Причина зміни",
    "Reason Name": "Назва причини",
    "Qualification": "Кваліфікація",
    "Seniority": "Стаж",
    "Tariff Grade": "Тарифний розряд",
    "Taxable (PDFO)": "Оподатковується (ПДФО)",

    # Employee & Company
    "Employee": "Працівник",
    "Company": "Компанія",
    "Department": "Підрозділ",
    "Job Position": "Посада",
    "Employment Type": "Тип зайнятості",
    "Diia.City Employee": "Працівник Дія.Сіті",
    "Employee under Diia.City special tax regime": "Працівник за спеціальним податковим режимом Дія.Сіті",
    "Work Mode": "Режим роботи",

    # Staffing
    "Staffing": "Штатний розпис",
    "Staffing Position": "Штатна позиція",

    # Hiring
    "Hiring": "Прийняття на роботу",
    "Create your first employment contract": "Створіть перший трудовий договір",
    "Additional Vacation Days": "Додаткові дні відпустки",
    "Additional vacation days based on work conditions": "Додаткові дні відпустки залежно від умов праці",

    # Messages & Activity (standard Odoo)
    "Action Needed": "Потрібна дія",
    "Activities": "Активності",
    "Activity Exception Decoration": "Оформлення виключення активності",
    "Activity State": "Стан активності",
    "Activity Type Icon": "Іконка типу активності",
    "Attachment Count": "Кількість вкладень",
    "Created by": "Створив",
    "Created on": "Створено",
    "Display Name": "Відображуване ім'я",
    "Followers": "Підписники",
    "Followers (Partners)": "Підписники (Партнери)",
    "Font awesome icon e.g. fa-tasks": "Іконка Font Awesome, напр. fa-tasks",
    "Has Message": "Має повідомлення",
    "Icon": "Іконка",
    "Icon to indicate an exception activity.": "Іконка для позначення виключної активності.",
    "ID": "ID",
    "If checked, new messages require your attention.": "Якщо позначено, нові повідомлення потребують вашої уваги.",
    "If checked, some messages have a delivery error.": "Якщо позначено, деякі повідомлення мають помилку доставки.",
    "Is Follower": "Є підписником",
    "Last Updated by": "Оновив",
    "Last Updated on": "Оновлено",
    "Message Delivery error": "Помилка доставки повідомлення",
    "Messages": "Повідомлення",
    "My Activity Deadline": "Термін моєї активності",
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
    "Type of the exception activity on record.": "Тип виключної активності в записі.",
    "Website communication history": "Історія комунікації веб-сайту",
    "Website Messages": "Повідомлення веб-сайту",

    # Mixin
    "HR Document Mixin": "Міксин HR-документа",

    # Other
    "None": "Немає",
    "Other": "Інше",
    "Contract Salary Change": "Зміна окладу за договором",
    "Currency": "Валюта",
    "Hazard classification class according to DSTU": "Клас шкідливості згідно з ДСТУ",

    # Version-based fields (Odoo 19)
    "Contract Type (UA)": "Тип договору (UA)",
    "UA Contract Type": "Тип договору UA",
    "Employee Contract": "Договір працівника",
    "Employee Version": "Версія договору працівника",
    "Version Allowance": "Надбавка версії договору",
    "Version Allowances": "Надбавки версії договору",
    "Version Amendment": "Додаткова угода до версії",
    "Version Salary Change": "Зміна окладу версії договору",
    "Termination Reason (UA)": "Причина звільнення (UA)",
    "Work Schedule (UA)": "Графік роботи (UA)",
    "Job Combining Count": "Кількість суміщень",
    "Track employees who perform duties of combined positions with surcharges.": "Відстеження працівників, які виконують обов'язки суміщуваних посад з доплатами.",
    "Status based on activities\\nOverdue: Due date is already passed\\nToday: Activity date is today\\nPlanned: Future activities.": "Статус на основі активностей\\nПрострочено: Термін вже минув\\nСьогодні: Активність на сьогодні\\nЗаплановано: Майбутні активності.",
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
                        i = j + 1
                        continue
                    elif msgstr_empty and msgid and is_english(msgid) and msgid not in TRANSLATIONS:
                        untranslated.append(msgid)

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
