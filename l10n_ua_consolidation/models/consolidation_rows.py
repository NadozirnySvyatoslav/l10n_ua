"""Row definitions of forms № 1-к / № 2-к and the per-company aggregator.

The rows are *not* a second mapping of the chart of accounts: they are built
from ``BALANCE_LINES`` (Form 1) and ``PNL_LINES`` (Form 2) of
``l10n_ua_accounting`` and only extended with what forms № 1-к / № 2-к
(додатки 1, 2 до НП(С)БО 1, наказ Мінфіну № 73) add on top of them:

* 1055 «Гудвіл при консолідації», 1490 «Неконтрольована частка» — rows that
  only consolidation entries fill;
* 2-к: 2470/2475 «Чистий прибуток, що належить власникам материнської
  компанії / неконтрольованій частці».

Form 1 itself carries 1030/1035 (рах. 141 / інші 14), 1425/1430 (46/45), the
contra accounts 131–135 and 38, classes 7–9 in 1420 (#386), and the
single-row sections 1200 and 1700 (#422). Its rows «у тому числі»
(``BALANCE_SUB_LINES``: 1001/1002, 1011/1012, 1136, 1621) are not carried
into 1-к.

Balance amounts are signed (assets = debit balance, equity and liabilities =
credit balance) and every account is assigned to exactly one row (the
longest matching prefix; prefixes shared by an asset and a liability row —
36, 37, 63, 641, 642, 643, 644, 68 — go by the sign of the balance per
account and partner; ПДВ 643/644 between 1190 and 1690).
Eliminations need this: a row built from ``abs()`` of a net balance cannot be
reduced by the intra-group part of it.

P&L amounts use exactly the Form 2 rule (credit turnover for income rows,
debit turnover for expense rows).
"""

from odoo.addons.l10n_ua_accounting.models.l10n_ua_balance_report import (
    ASSET_SECTIONS, BALANCE_LINES, LIABILITY_SECTIONS,
)
from odoo.addons.l10n_ua_accounting.models.l10n_ua_pnl_report import PNL_LINES

# Rows of form 1-к that Form 1 of l10n_ua_accounting does not have.
# (sequence, key, name, code, section, prefixes)
_BALANCE_EXTRA_ROWS = [
    (165, 'goodwill', 'Гудвіл при консолідації', '1055', 'asset_noncurrent', []),
    (480, 'nci', 'Неконтрольована частка', '1490', 'equity', []),
]

# Rows of form 2-к after 2350. (sequence, key, name, code)
_PNL_EXTRA_ROWS = [
    (1600, 'np_owners', 'Чистий прибуток (збиток), що належить власникам материнської компанії', '2470'),
    (1610, 'np_nci', 'Чистий прибуток (збиток), що належить неконтрольованій частці', '2475'),
]


def _prefixes(codes):
    return [c.strip() for c in (codes or '').split(',') if c.strip()]


def _build_balance_rows():
    rows = []
    for seq, key, name, code, section, line_type, acct_codes, _bal in BALANCE_LINES:
        rows.append({
            'sequence': seq,
            'key': key,
            'name': name,
            'code': code,
            'section': section or False,
            'line_type': line_type,
            'prefixes': _prefixes(acct_codes),
        })
    for seq, key, name, code, section, prefixes in _BALANCE_EXTRA_ROWS:
        rows.append({
            'sequence': seq,
            'key': key,
            'name': name,
            'code': code,
            'section': section,
            'line_type': 'detail',
            'prefixes': list(prefixes),
        })
    rows.sort(key=lambda r: r['sequence'])
    return rows


def _build_pnl_rows():
    rows = []
    for seq, key, name, code, line_type, acct_codes, turnover in PNL_LINES:
        rows.append({
            'sequence': seq * 10,
            'key': key,
            'name': name,
            'code': code,
            'section': False,
            'line_type': line_type,
            'prefixes': _prefixes(acct_codes),
            'turnover': turnover,
        })
    for seq, key, name, code in _PNL_EXTRA_ROWS:
        rows.append({
            'sequence': seq,
            'key': key,
            'name': name,
            'code': code,
            'section': False,
            'line_type': 'attribution',
            'prefixes': [],
            'turnover': '',
        })
    rows.sort(key=lambda r: r['sequence'])
    return rows


BALANCE_ROWS = _build_balance_rows()
PNL_ROWS = _build_pnl_rows()
BALANCE_ROW_BY_KEY = {r['key']: r for r in BALANCE_ROWS}
PNL_ROW_BY_KEY = {r['key']: r for r in PNL_ROWS}
BALANCE_DETAIL_ROWS = [r for r in BALANCE_ROWS if r['line_type'] == 'detail']
PNL_DETAIL_ROWS = [r for r in PNL_ROWS if r['line_type'] == 'detail']
EQUITY_DETAIL_KEYS = [r['key'] for r in BALANCE_DETAIL_ROWS
                      if r['section'] == 'equity' and r['key'] != 'nci']


def balance_side(row):
    return 'asset' if row['section'] in ASSET_SECTIONS else 'liability'


def match_balance_row(code, amount):
    """Return the key of the 1-к detail row an account code belongs to.

    Longest matching prefix wins; when it is shared by an asset and a
    liability row (36, 37, 63, 641, 642, 643, 644, 68), a debit balance goes to the asset row and a
    credit balance to the liability row. ``None`` = unmapped.
    """
    best_len = 0
    candidates = []
    for row in BALANCE_DETAIL_ROWS:
        for prefix in row['prefixes']:
            if code.startswith(prefix):
                if len(prefix) > best_len:
                    best_len = len(prefix)
                    candidates = [row]
                elif len(prefix) == best_len and row not in candidates:
                    candidates.append(row)
    if not candidates:
        return None
    if len(candidates) > 1:
        wanted = 'asset' if amount >= 0 else 'liability'
        for row in candidates:
            if balance_side(row) == wanted:
                return row['key']
    return candidates[0]['key']


def match_pnl_row(code):
    best_len = 0
    best = None
    for row in PNL_DETAIL_ROWS:
        for prefix in row['prefixes']:
            if code.startswith(prefix) and len(prefix) > best_len:
                best_len = len(prefix)
                best = row['key']
    return best


def complete_balance(details):
    """Fill subtotals and totals of 1-к from a {detail_key: amount} dict."""
    amounts = {r['key']: details.get(r['key'], 0.0) for r in BALANCE_DETAIL_ROWS}
    section_totals = {}
    for row in BALANCE_DETAIL_ROWS:
        section_totals[row['section']] = section_totals.get(row['section'], 0.0) + amounts[row['key']]
    for row in BALANCE_ROWS:
        if row['line_type'] == 'subtotal':
            amounts[row['key']] = section_totals.get(row['section'], 0.0)
        elif row['line_type'] == 'section':
            amounts[row['key']] = 0.0
    amounts['total_assets'] = sum(section_totals.get(s, 0.0) for s in ASSET_SECTIONS)
    amounts['total_liabilities'] = sum(section_totals.get(s, 0.0) for s in LIABILITY_SECTIONS)
    return amounts


def complete_pnl(details):
    """Fill subtotals/total of 2-к the way Form 2 does: each subtotal is the
    running result of all detail rows above it (income +, expense −)."""
    amounts = {}
    running = 0.0
    for row in PNL_ROWS:
        if row['line_type'] == 'detail':
            value = details.get(row['key'], 0.0)
            amounts[row['key']] = value
            running += value if row['turnover'] == 'credit' else -value
        elif row['line_type'] in ('subtotal', 'total'):
            amounts[row['key']] = running
        else:
            amounts[row['key']] = details.get(row['key'], 0.0)
    return amounts
