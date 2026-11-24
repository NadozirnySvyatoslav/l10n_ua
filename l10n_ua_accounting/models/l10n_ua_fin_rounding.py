"""Units of the financial statements.

The full forms of НП(С)БО 1 (№ 1–№ 5) are filled in thousands of hryvnias
without decimals (DGdecimal0 in the XSD), the simplified forms of НП(С)БО 25
with one decimal (DGdecimal1). A row is rounded half away from zero; the
totals of a form are added up from its rounded rows, so that the arithmetic
the controls of ДПС check holds on the printed and the submitted form.
"""

from odoo.tools import float_round


def to_thousands(amount, digits=0):
    """Hryvnias → thousands of hryvnias, rounded half away from zero."""
    return float_round((amount or 0.0) / 1000.0, precision_digits=digits,
                       rounding_method='HALF-UP')


def round_units(amount, digits=0):
    """Round an amount already in thousands (a sum of rounded rows)."""
    return float_round(amount or 0.0, precision_digits=digits, rounding_method='HALF-UP')


def format_units(amount, digits=0, parentheses=True):
    """'1234', '(56)' for a negative amount, '–' for nothing: the printed form."""
    if not amount:
        return '–'
    text = f'%.{digits}f' % abs(amount)
    if amount < 0:
        return f'({text})' if parentheses else f'-{text}'
    return text
