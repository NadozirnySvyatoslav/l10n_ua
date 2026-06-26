#!/usr/bin/env python3
"""Translate PO file for l10n_ua_hr_documents module."""

TRANSLATIONS = {
    # Order Types
    "HR Order": "Кадровий наказ",
    "HR Orders": "Кадрові накази",
    "HR Order Template": "Шаблон кадрового наказу",
    "HR Order Template Selection Wizard": "Майстер вибору шаблону наказу",
    "HR Order Type": "Тип кадрового наказу",
    "Order": "Наказ",
    "Order Date": "Дата наказу",
    "Order Number": "Номер наказу",
    "Order Templates": "Шаблони наказів",
    "Order Type": "Тип наказу",
    "Order Types": "Типи наказів",
    "Order type code must be unique!": "Код типу наказу повинен бути унікальним!",
    "Create your first order template": "Створіть перший шаблон наказу",
    "Templates help you quickly fill in standard order content.": "Шаблони допомагають швидко заповнити стандартний зміст наказу.",

    # Order Types Values
    "Hiring": "Прийняття на роботу",
    "Dismissal": "Звільнення",
    "Transfer": "Переведення",
    "Vacation": "Відпустка",
    "Bonus": "Преміювання",
    "Sick Leave": "Лікарняний",
    "Business Trip": "Відрядження",
    "Disciplinary": "Дисциплінарне стягнення",
    "Termination": "Звільнення",
    "Other": "Інше",

    # Template Fields
    "Template": "Шаблон",
    "Template Body": "Тіло шаблону",
    "Template Name": "Назва шаблону",
    "Content Template": "Шаблон змісту",
    "HTML template for the order body": "HTML-шаблон для тіла наказу",
    "Load from Template": "Завантажити з шаблону",
    "Select Template": "Вибрати шаблон",

    # Template Requirements
    "Requires Contract": "Потребує договір",
    "Requires Date Range": "Потребує діапазон дат",
    "Requires Department": "Потребує підрозділ",
    "Requires Employee": "Потребує працівника",

    # Order Content
    "Subject": "Тема",
    "Content": "Зміст",
    "Body": "Тіло",
    "Number": "Номер",
    "Date": "Дата",
    "Date From": "Дата з",
    "Date To": "Дата до",

    # Hiring Order Fields
    "Employment Start Date": "Дата початку працевлаштування",
    "Employment End Date": "Дата закінчення працевлаштування",
    "Fixed-term Contract": "Строковий трудовий договір",
    "Employment Type": "Тип зайнятості",
    "Main place of work": "За основним місцем роботи",
    "Concurrent employment": "За сумісництвом",

    # Sync errors
    "Cannot update the employee contract: this employee already has an active contract during the selected period.\n\nPlease either:\n- Change the start date so that it does not overlap with the existing contract, or\n- Create a new employee if this employee should have multiple active contracts.": "Не вдалось оновити контракт співробітника: цей співробітник уже має активний контракт у вибраному періоді.\n\nБудь ласка:\n- Змініть дату початку, щоб вона не перетиналася з існуючим контрактом, або\n- Створіть нового співробітника, якщо у цього співробітника має бути декілька активних контрактів.",
    "Failed to sync hiring order data to the employee record.\n\nDetails: %s": "Не вдалось синхронізувати дані наказу з карткою співробітника.\n\nПодробиці: %s",

    # Placeholders in templates
    "<strong>Підрозділ:</strong>": "<strong>Підрозділ:</strong>",
    "<strong>Посада:</strong>": "<strong>Посада:</strong>",
    "<strong>Працівник:</strong>": "<strong>Працівник:</strong>",
    "<strong>Тема:</strong>": "<strong>Тема:</strong>",
    "'Наказ_%s_%s' % (object.name, object.date)": "'Наказ_%s_%s' % (object.name, object.date)",
    "(П.І.Б.)": "(П.І.Б.)",
    "(підпис)": "(підпис)",

    # Personal File
    "Personal File": "Особова справа",
    "Personal Files": "Особові справи",
    "Personal File Document": "Документ особової справи",
    "Personal file for this employee already exists!": "Особова справа для цього працівника вже існує!",
    "Create a personal file for an employee": "Створити особову справу для працівника",
    "File Number": "Номер справи",

    # Documents
    "Documents": "Документи",
    "Document Name": "Назва документа",
    "Document Number": "Номер документа",
    "Document Type": "Тип документа",
    "Attachment": "Вкладення",

    # Work History
    "Work History": "Трудова історія",
    "Work History Entry": "Запис трудової історії",
    "Entry Type": "Тип запису",
    "Organization": "Організація",
    "Position": "Посада",

    # Family
    "Family": "Сім'я",
    "Family Member": "Член сім'ї",
    "Family Members": "Члени сім'ї",
    "Relation": "Ступінь споріднення",
    "Full Name": "Повне ім'я",
    "Birth Date": "Дата народження",
    "Birth Place": "Місце народження",
    "Parent": "Батько/Мати",
    "Spouse": "Чоловік/Дружина",
    "Child": "Дитина",

    # Marital Status
    "Marital Status": "Сімейний стан",
    "Single": "Неодружений/а",
    "Married": "Одружений/а",
    "Divorced": "Розлучений/а",
    "Widowed": "Вдівець/вдова",

    # Education
    "Education": "Освіта",
    "Education Level": "Рівень освіти",
    "Educational Institution": "Навчальний заклад",
    "Diploma": "Диплом",
    "Graduation Year": "Рік закінчення",
    "Specialty": "Спеціальність",
    "Qualification": "Кваліфікація",
    "Basic Secondary": "Базова середня",
    "Complete Secondary": "Повна середня",
    "Vocational": "Професійно-технічна",
    "Incomplete Higher": "Неповна вища",
    "Basic Higher (Bachelor)": "Базова вища (бакалавр)",
    "Complete Higher (Master/Specialist)": "Повна вища (магістр/спеціаліст)",
    "PhD": "Кандидат наук",
    "Doctor of Sciences": "Доктор наук",

    # Military
    "Military": "Військовий облік",
    "Military Document": "Військовий документ",
    "Military Rank": "Військове звання",
    "Military Specialty": "Військова спеціальність",
    "Military Status": "Військовий статус",
    "Liable for Military Service": "Військовозобов'язаний",
    "Not Liable": "Невійськовозобов'язаний",
    "Reservist": "Резервіст",
    "Retired": "У відставці",

    # Identity Documents
    "Passport": "Паспорт",
    "ID Card": "ID-картка",
    "RNOKPP Certificate": "Довідка РНОКПП",
    "Medical Certificate": "Медична довідка",
    "Issue Date": "Дата видачі",
    "Issued By": "Ким видано",
    "Valid Until": "Дійсний до",
    "Citizenship": "Громадянство",
    "Photo": "Фото",

    # Status & States
    "Status": "Статус",
    "Draft": "Чернетка",
    "Confirmed": "Підтверджено",
    "Cancelled": "Скасовано",
    "Active": "Активний",
    "Archived": "Архівовано",

    # Actions
    "Apply": "Застосувати",
    "Cancel": "Скасувати",
    "Confirm": "Підтвердити",
    "Set to Draft": "Повернути в чернетку",

    # Menu items
    "Documents": "Документи",

    # Common Fields
    "Name": "Назва",
    "Code": "Код",
    "Description": "Опис",
    "Notes": "Примітки",
    "Sequence": "Послідовність",
    "Category": "Категорія",
    "Company": "Компанія",
    "Employee": "Працівник",
    "Department": "Підрозділ",
    "Job Position": "Посада",
    "Certificate": "Довідка",

    # Multi-line strings
    "HR orders include hiring, dismissal, transfer, vacation, and other personnel documents.": "Кадрові накази включають прийняття, звільнення, переведення, відпустку та інші кадрові документи.",

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
