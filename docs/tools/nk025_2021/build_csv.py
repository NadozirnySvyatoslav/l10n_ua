"""Build the NK 025:2021 CSV for l10n_ua_medecin_clinical from extracted PDF data.

Inputs: sec5.json (parse_sec5.py), tab_rows.json (extract_tab.py). Output: CSV + report.
CSV columns: code,name,level,parent_code,block
"""
import collections
import csv
import json
import re
import sys

sec5_path, tab_path, out_csv = sys.argv[1:4]
sec5 = json.load(open(sec5_path))
tab = json.load(open(tab_path))

HOMO = str.maketrans('АВСЕНКМОРТХ', 'ABCEHKMOPTX')
CODE3 = re.compile(r'^[A-Z]\d\d$')
CODE4 = re.compile(r'^[A-Z]\d\d\.\d$')
CODE5 = re.compile(r'^[A-Z]\d\d\.\d\d$')
report = collections.defaultdict(list)


def ncode(c):
    c = (c or '').strip()
    f = re.sub(r'\s+', '', c).translate(HOMO).rstrip('†*')
    if f != c and c not in ('-',):
        report['code_normalized'].append(c)
    return f


def join_text(parts):
    out = ''
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif out.endswith('-'):
            out += p
        else:
            out += ' ' + p
    return re.sub(r'\s+', ' ', out).strip()


def cell_text(c):
    return join_text((c or '').split('\n'))


# --- 1. tabular rows, merging page-break continuations ---------------------
above = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else {}
rows = []
last_page = None
for r in tab:
    if r['page'] != last_page:
        cont = above.get(str(r['page']))
        last_page = r['page']
        if isinstance(cont, list) and cont and isinstance(cont[0], list):
            head, extra = cont[0], cont[1:]
            if rows:
                prev = rows[-1]
                for i in (1, 3, 5):
                    if head[i].strip():
                        prev[i] = join_text([prev[i], head[i]])
                for i in (0, 2, 4):
                    if head[i].strip():
                        report['continuation_with_code'].append((r['page'], head))
            for g in extra:
                rows.append([ncode(g[0]), join_text([g[1]]), ncode(g[2]) or '-', join_text([g[3]]),
                             ncode(g[4]) or '-', join_text([g[5]]), r['page']])
                report['rows_recovered_above_table'].append(r['page'])
        elif cont:
            report['continuation_unparsed'].append((r['page'], cont))
    cells = r['cells']
    if len(cells) != 6:
        report['bad_width'].append((r['page'], cells))
        continue
    if any('Код' in (c or '') or 'Назва' in (c or '') for c in cells):
        continue  # header
    c3 = ncode(cells[0])
    if not c3:
        if not rows:
            report['orphan_continuation'].append((r['page'], cells))
            continue
        prev = rows[-1]
        for i in (1, 3, 5):
            if cells[i].strip():
                prev[i] = join_text([prev[i], cell_text(cells[i])])
        for i in (2, 4):
            if cells[i].strip():
                report['continuation_with_code'].append((r['page'], cells))
        continue
    rows.append([c3, cell_text(cells[1]), ncode(cells[2]), cell_text(cells[3]),
                 ncode(cells[4]), cell_text(cells[5]), r['page']])

nodes = {}   # code -> dict
order = []


def add(code, name, level, parent, page=None):
    if code in nodes:
        n = nodes[code]
        n['variants'][name] += 1
        if n['name'] != name:
            report['name_conflict'].append((code, n['name'], name, page))
            n['name'] = max(n['variants'], key=lambda v: n['variants'][v])
        return
    nodes[code] = {'code': code, 'name': name, 'level': level, 'parent_code': parent,
                   'variants': collections.Counter([name])}
    order.append(code)


tab_c3_var = collections.defaultdict(collections.Counter)
for c3, n3, c4, n4, c5, n5, page in rows:
    if not CODE3.match(c3):
        report['bad_code3'].append((page, c3, n3))
        continue
    tab_c3_var[c3][n3] += 1
    if c4 in ('-', ''):
        continue
    if not CODE4.match(c4):
        report['bad_code4'].append((page, c4, n4))
        continue
    if not c4.startswith(c3):
        report['code4_not_in_code3'].append((page, c3, c4))
    add(c4, n4, 'subcategory', c3, page)
    if c5 in ('-', ''):
        continue
    if not CODE5.match(c5):
        report['bad_code5'].append((page, c5, n5))
        continue
    if not c5.startswith(c4):
        report['code5_not_in_code4'].append((page, c4, c5))
    add(c5, n5, 'subcategory5', c4, page)

tab_c3_names = {c: max(v, key=lambda x: (v[x], len(x))) for c, v in tab_c3_var.items()}

# --- 2. chapters / blocks / 3-char categories from section 5 ---------------
headers = sec5['headers']


def in_ranges(code, ranges):
    return any(a <= code <= b for a, b in ranges)


def span(h):
    return sum((ord(b[0]) * 100 + int(b[1:])) - (ord(a[0]) * 100 + int(a[1:])) for a, b in h['ranges'])


for h in headers:
    if h['kind'] == 'chapter':
        h['code'] = 'Клас %02d' % h['num']
    else:
        h['code'] = ', '.join('%s-%s' % tuple(r) for r in h['ranges'])

# chapter of each header: the chapter preceding it in document order
chap = None
for h in headers:
    if h['kind'] == 'chapter':
        chap = h
    h['chapter'] = chap

blocks = [h for h in headers if h['kind'] == 'block']
for h in headers:
    if h['kind'] == 'chapter':
        h['parent'] = None
        continue
    cands = [b for b in blocks if b is not h and b['chapter'] is h['chapter']
             and all(in_ranges(a, b['ranges']) and in_ranges(z, b['ranges']) for a, z in h['ranges'])
             and span(b) > span(h)]
    h['parent'] = min(cands, key=span)['code'] if cands else h['chapter']['code']

dup = [c for c, n in collections.Counter(h['code'] for h in headers).items() if n > 1]
if dup:
    report['duplicate_header_codes'] = dup

csv_rows = []
for h in headers:
    csv_rows.append({'code': h['code'], 'name': h['title'], 'level': h['kind'],
                     'parent_code': h['parent'] or '', 'block': ''})

leaf_blocks = {}
seen3 = set()
for code, name, hidx in sec5['cats']:
    if code in seen3:
        report['dup_cat'].append(code)
        continue
    seen3.add(code)
    # the block the category is listed under in the document
    parent = headers[hidx]['code']
    if not in_ranges(code, headers[hidx]['ranges']):
        report['cat_outside_its_block_range'].append((code, parent))
    leaf_blocks[code] = parent
    csv_rows.append({'code': code, 'name': name, 'level': 'category',
                     'parent_code': parent, 'block': parent})
    if code in tab_c3_names and tab_c3_names[code] != name:
        report['cat_name_differs_sec5_vs_tab'].append((code, name, tab_c3_names[code]))

for c in sorted(tab_c3_names):
    if c not in seen3:
        cands = [b for b in blocks if in_ranges(c, b['ranges'])]
        parent = min(cands, key=span)['code'] if cands else ''
        report['tab_cat_missing_in_sec5_added_from_tab'].append((c, tab_c3_names[c], parent))
        seen3.add(c)
        leaf_blocks[c] = parent
        csv_rows.append({'code': c, 'name': tab_c3_names[c], 'level': 'category',
                         'parent_code': parent, 'block': parent})

children = collections.Counter(n['parent_code'] for n in nodes.values())
for code in order:
    n = nodes[code]
    blk = leaf_blocks.get(code[:3], '')
    csv_rows.append({'code': code, 'name': n['name'], 'level': n['level'],
                     'parent_code': n['parent_code'], 'block': blk})
    if n['parent_code'] not in nodes and n['parent_code'] not in seen3:
        report['missing_parent'].append((code, n['parent_code']))

names = {r['code']: r['name'] for r in csv_rows}
for r in csv_rows:
    if not r['name'] or r['name'] == '-':
        r['name'] = names.get(r['parent_code']) or r['code']
        report['empty_name_filled_from_parent'].append((r['code'], r['name']))
        names[r['code']] = r['name']

# --- 3. repair words split by narrow-column line wraps ("внутрішньочеревн е")
WORD = re.compile(r"[\w'’]+")
vocab = collections.Counter()
for r in csv_rows:
    vocab.update(w.lower() for w in WORD.findall(r['name']))
for c in sec5['cats']:
    vocab.update(w.lower() for w in WORD.findall(c[1]))
SHORT_OK = set('в у з і й а о та чи ні не де ла ле ді фон ван дю'.split())


def repair(name):
    toks = name.split(' ')
    out = []
    for t in toks:
        if out:
            a, b = out[-1], t
            ca, cb = a.strip(',.;:()[]«»').lower(), b.strip(',.;:()[]«»').lower()
            joined = (a + b).strip(',.;:()[]«»').lower()
            if (cb and cb[0].isalpha() and cb[0].islower() and b[0].islower()
                    and vocab.get(joined, 0) >= 1 and joined not in (ca, cb)
                    and (vocab.get(cb, 0) <= 1 and cb not in SHORT_OK or vocab.get(ca, 0) <= 1)
                    or (cb and len(cb) <= 2 and b[0].isalpha() and b[0].islower()
                        and cb not in SHORT_OK and vocab.get(cb, 0) <= 3
                        and a[-1].isalpha() and vocab.get(ca, 0) <= 2 and len(ca) >= 5)):
                out[-1] = a + b
                report['split_word_repaired'].append((a, b))
                continue
        out.append(t)
    return ' '.join(out)


for r in csv_rows:
    r['name'] = repair(r['name'])

with open(out_csv, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['code', 'name', 'level', 'parent_code', 'block'],
                       lineterminator='\n')
    w.writeheader()
    w.writerows(csv_rows)

lv = collections.Counter(r['level'] for r in csv_rows)
print('rows', len(csv_rows), dict(lv))
for k, v in report.items():
    print('==', k, len(v))
    for x in v[:15]:
        print('   ', x)
