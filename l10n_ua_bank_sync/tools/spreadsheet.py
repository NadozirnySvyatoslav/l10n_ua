"""Спільне читання табличних виписок (XLS / XLSX) для файлових провайдерів.

Провайдери (privat, otp, …) не копіюють читання Excel, а беруть рядки
звідси й розбирають власну розкладку колонок. Бібліотеки імпортуються
ліниво: sync не вимагає xlrd/openpyxl, їх оголошує у external_dependencies
провайдер, який читає Excel.
"""

import io

# OLE2 Compound File — контейнер старого XLS (BIFF8).
XLS_MAGIC = b'\xd0\xcf\x11\xe0'


def is_xls(content):
    """Чи байти схожі на XLS (BIFF8, OLE2)."""
    return content[:4] == XLS_MAGIC


def read_xls_rows(content, sheet_index=0):
    """Рядки першого (або sheet_index) аркуша XLS як списки значень клітинок."""
    import xlrd
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(sheet_index)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def read_xlsx_rows(content):
    """Рядки активного аркуша XLSX; порожні клітинки — ''."""
    import openpyxl
    wb = openpyxl.load_workbook(
        io.BytesIO(content), read_only=True, data_only=True)
    try:
        return [[('' if v is None else v) for v in row]
                for row in wb.active.iter_rows(values_only=True)]
    finally:
        wb.close()
