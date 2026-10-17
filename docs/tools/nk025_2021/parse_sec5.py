"""Parse section 5 (Перелік тризначних рубрик) of NK 025:2021 text (pdftotext -layout).

Outputs JSON {headers: [{kind, num?, title, ranges:[[a,b],...]}], cats: [[code, name]]}
"""
import json
import re
import sys

txt_path, out_path = sys.argv[1], sys.argv[2]
lines = open(txt_path, encoding='utf-8').read().replace('\x0c', '').split('\n')

start = next(i for i, l in enumerate(lines) if l.strip() == 'КЛАС 1')
end = next(i for i, l in enumerate(lines) if '6. ТАБЛИЧНИЙ ПЕРЕЛІК ХВОРОБ' in l)

# Cyrillic homoglyphs that occasionally appear in code positions of the source
HOMO = str.maketrans('АВСЕНКМОРТХ', 'ABCEHKMOPTX')
L = r'[A-ZАВСЕНКМОРТХ]'
CAT = re.compile(rf'^({L}\d\d)[†*]?\s+(\S.*)$')
RANGE_END = re.compile(rf'\(({L}\d\d(?:\s*[-–]\s*{L}\d\d)?(?:\s*,\s*{L}\d\d\s*[-–]\s*{L}\d\d)*)\)\s*$')
CHAP = re.compile(r'^КЛАС\s+(\d+)$')

headers, cats, homoglyph_fixes = [], [], []
buf, cur_cat, chap_num = [], None, None
last_cat, buf_after_cat, report_tail = None, False, []


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def code_fix(c):
    f = c.translate(HOMO)
    if f != c:
        homoglyph_fixes.append(c)
    return f


for raw in lines[start:end]:
    s = raw.strip()
    if not s:
        cur_cat = None
        continue
    if re.fullmatch(r'\d+', s):
        continue
    m = CHAP.match(s)
    if m:
        chap_num, buf, cur_cat = int(m.group(1)), [], None
        continue
    m = CAT.match(raw)
    if m and buf and last_cat is not None and buf_after_cat:
        # unindented wrapped tail of the previous category, not a header
        last_cat[1] = norm(last_cat[1] + ' ' + ' '.join(buf))
        report_tail.append(last_cat[0])
        buf = []
    if m and not buf:
        cur_cat = [code_fix(m.group(1)), norm(m.group(2)), headers[-1]['code_tmp']]
        cats.append(cur_cat)
        last_cat = cur_cat
        continue
    if cur_cat is not None and not buf and raw.startswith('      '):
        cur_cat[1] = norm(cur_cat[1] + ' ' + s)
        continue
    if not buf:
        buf_after_cat = cur_cat is not None
    cur_cat = None
    buf.append(s)
    joined = norm(' '.join(buf))
    rm = RANGE_END.search(joined)
    if rm:
        ranges = [[code_fix(x) for x in re.split(r'\s*[-–]\s*', r.strip())]
                  for r in rm.group(1).split(',')]
        ranges = [r if len(r) == 2 else [r[0], r[0]] for r in ranges]
        h = {'title': norm(joined[:rm.start()]), 'ranges': ranges, 'code_tmp': len(headers)}
        buf_after_cat = False
        if chap_num is not None:
            h.update(kind='chapter', num=chap_num)
            chap_num = None
        else:
            h['kind'] = 'block'
        headers.append(h)
        buf = []

json.dump({'headers': headers, 'cats': cats}, open(out_path, 'w'), ensure_ascii=False, indent=0)
print('headers', len(headers), 'chapters', sum(h['kind'] == 'chapter' for h in headers),
      'cats', len(cats), 'leftover', buf, 'homoglyphs fixed', homoglyph_fixes, 'unindented tails', report_tail)
