"""Імпорт кадрового «Списку працівників» (ПІБ, посада, ДН, адреса, телефон, дата прийняття).

Такий список зазвичай ведуть у Word і оновлюють до початку навчального року.
Скрипт доповнює ним картки працівників: заповнює лише порожні реквізити й
ніколи не перезаписує те, що вже внесено в Odoo.

Запуск:
    soffice --headless --convert-to txt "СПИСОК працівників.doc"   # якщо .doc
    # далі — розкласти у CSV: fio, position, birth, address, phone, hired
    sudo -u odoo HOME=/tmp /opt/odoo/venv/bin/odoo shell \\
        -c /opt/odoo/odoo.conf -d <db> --no-http < import_staff_list.py

Змінні середовища:
    STAFF_CSV    — шлях до CSV (типово /opt/odoo/import_data/staff.csv)
    STAFF_APPLY  — «1», щоб записати зміни
    STAFF_CREATE — «1», щоб завести відсутніх у базі працівників
    STAFF_ONLY   — перелік прізвищ через кому: обробити лише цих людей
                   (щоб завести окремих працівників, не чіпаючи решту списку)
"""

import csv
import os
import re
from datetime import datetime

CSV_PATH = os.environ.get('STAFF_CSV', '/opt/odoo/import_data/staff.csv')
APPLY = os.environ.get('STAFF_APPLY') == '1'
CREATE = os.environ.get('STAFF_CREATE') == '1'
ONLY = [part.strip().lower() for part in
        os.environ.get('STAFF_ONLY', '').split(',') if part.strip()]

DATE_RE = re.compile(r'(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})')
# Позначки в дужках («(строковий)», «(за сумісництвом)») — це умови роботи,
# а не частина ПІБ, тож для зіставлення їх прибираємо.
NOTE_RE = re.compile(r'\([^)]*\)')
# Але сама позначка сумісництва не викидається: у списку вона єдине джерело
# відомостей про те, що це не основне місце роботи. Шукаємо корінь, бо в
# списках трапляється і «(за сумісництвом)», і «(сумісник)», і «сумісн.».
SECONDARY_RE = re.compile(r'сумісн', re.IGNORECASE)


# Апостроф у ПІБ трапляється в п'яти накресленнях, і кожне ламає зіставлення
# («Лук´янчук» проти «Лук'янчук»). Зводимо всі до прямого.
APOSTROPHES = str.maketrans({c: "'" for c in "\u2019\u0060\u00b4\u02bc\u2018\u02bb"})


def norm(text):
    return re.sub(r'\s+', ' ', (text or '')).translate(APOSTROPHES).strip()


def parse_date(text):
    match = DATE_RE.search(text or '')
    if not match:
        return False
    day, month, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).date()
    except ValueError:
        return False


def clean_name(text):
    return norm(NOTE_RE.sub('', text or ''))


def name_keys(full_name):
    parts = clean_name(full_name).lower().replace('.', ' ').split()
    if not parts:
        return []
    surname = parts[0]
    initials = ''.join(part[0] for part in parts[1:3])
    keys = []
    if len(initials) > 1:
        keys.append((surname, initials))
    if initials:
        keys.append((surname, initials[0]))
    return keys or [(surname, '')]


def _unshift(row):
    """Полагодити рядок, у якому в Word злилися комірки «посада» і «дата народження».

    Тоді посада приїжджає разом із датою («Викладач 30.10.1982»), а решта
    колонок з'їжджає на одну вліво — телефон опиняється в адресі, дата
    прийняття в телефоні. Ознака зсуву однозначна: у «даті народження» немає
    дати, зате вона є в кінці посади.
    """
    position, birth = row.get('position', ''), row.get('birth', '')
    tail = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})\s*$', position or '')
    if not tail or parse_date(birth):
        return
    row['position'] = norm(position[:tail.start()])
    row['hired'] = row.get('phone', '')
    row['phone'] = row.get('address', '')
    row['address'] = birth
    row['birth'] = tail.group(1)


def canonical_job(title):
    title = norm(title).rstrip('.,;')
    return (title[0].upper() + title[1:]) if title else ''


def main():
    Employee = env['hr.employee'].with_context(active_test=False)
    Job = env['hr.job']

    jobs = {job.name.strip().lower(): job for job in Job.search([])}
    index = {}
    for employee in Employee.search([]):
        for key in name_keys(employee.name):
            index.setdefault(key, []).append(employee)

    with open(CSV_PATH, encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))

    stats = {'ПІБ у файлі': len(rows)}
    filled = {'посада': 0, 'дата народження': 0, 'адреса': 0,
              'телефон': 0, 'дата прийняття': 0, 'сумісництво': 0}
    # Поле додає l10n_ua_hr_contract, від якого цей модуль не залежить.
    has_employment_type = 'employment_type_ua' in Employee._fields
    missing, ambiguous, created, seen = [], [], [], set()
    new_records = Employee.browse()

    for row in rows:
        _unshift(row)

    if ONLY:
        rows = [row for row in rows
                if any(part in row['fio'].lower() for part in ONLY)]

    for row in rows:
        full_name = clean_name(row['fio'])
        candidates = []
        for key in name_keys(full_name):
            candidates = index.get(key, [])
            if candidates:
                break
        if len(candidates) > 1:
            ambiguous.append((full_name, [c.name for c in candidates]))
            continue
        employee = candidates[0] if candidates else None

        if not employee:
            missing.append(full_name)
            if not (APPLY and CREATE):
                continue
            employee = Employee.create({'name': full_name})
            new_records |= employee
            created.append(full_name)
            for key in name_keys(full_name):
                index.setdefault(key, []).append(employee)
        seen.add(employee.id)

        values = {}
        job_name = canonical_job(row['position'])
        if job_name and not employee.job_id:
            job = jobs.get(job_name.lower())
            if not job and APPLY:
                job = Job.create({'name': job_name})
                jobs[job_name.lower()] = job
            if job:
                values['job_id'] = job.id
            filled['посада'] += 1

        birthday = parse_date(row['birth'])
        if birthday and not employee.birthday:
            values['birthday'] = birthday
            filled['дата народження'] += 1

        address = norm(row['address'])
        if address and not employee.private_street:
            values['private_street'] = address
            filled['адреса'] += 1
        if address and not employee.registration_street:
            values['registration_street'] = address

        phone = norm(row['phone'])
        if phone and not employee.private_phone:
            values['private_phone'] = phone
            filled['телефон'] += 1

        # Позначку сумісництва ставлять і біля ПІБ, і біля посади, тож
        # дивимось в обидві колонки. Записуємо лише поверх «основної
        # роботи»: це типове значення поля, а не свідомий вибір кадровика,
        # тоді як уже проставлене сумісництво — свідомий, і його скрипт не
        # чіпає, за загальним правилом «не перезаписувати внесене».
        #
        # Вид сумісництва зі списку не видно, тож ставимо зовнішнє: воно
        # переважає, а внутрішнє оформлюють наказом, який кадровик і так
        # вносить. Кількість таких записів друкується наприкінці — їх варто
        # переглянути.
        if has_employment_type and SECONDARY_RE.search(
                '%s %s' % (row['fio'], row.get('position', ''))):
            if employee.employment_type_ua == 'primary':
                values['employment_type_ua'] = 'external'
                filled['сумісництво'] += 1

        # «01.02.2025-30.06.2026» — це строковий договір: датою прийняття
        # береться початок періоду, кінець лишається у кадровій версії.
        hired = parse_date(row['hired'])
        if hired and not employee.hire_date:
            values['hire_date'] = hired
            filled['дата прийняття'] += 1


        if APPLY and values:
            employee.write(values)
            # Нова картка отримує версію договору, датовану днем створення, і
            # тоді працівник випадає зі зрізів на попередні дати. Датою версії
            # має бути прийняття на роботу — саме за нею Списки визначають,
            # хто працював на дату документа.
            if employee in new_records and hired:
                employee.current_version_id.date_version = hired

    print('=== ІМПОРТ СПИСКУ ПРАЦІВНИКІВ ===')
    for key, value in stats.items():
        print('%-26s %s' % (key, value))
    print('%-26s %s' % ('зіставлено', len(seen)))
    print('%-26s %s' % ('немає в Odoo', len(missing)))
    for name in missing:
        print('   —', name)
    if ambiguous:
        print('%-26s %s' % ('неоднозначних', len(ambiguous)))
        for name, options in ambiguous:
            print('   ?', name, '→', options)
    if created:
        print('%-26s %s' % ('створено працівників', len(created)))
    print('--- заповнено полів ---')
    for key, value in filled.items():
        print('   %-22s %s' % (key, value))
    if filled['сумісництво']:
        print('   ! сумісництво проставлено як зовнішнє — перевірте тих, '
              'хто суміщає посади в цій же установі')
    print('режим:', 'ЗАПИС' if APPLY else 'сухий прогін (STAFF_APPLY=1)',
          '| створення:', 'так' if CREATE else 'ні')
    if APPLY:
        env.cr.commit()
        print('зміни збережено')


main()
