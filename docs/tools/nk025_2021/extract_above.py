"""For each page of the tabular list, collect words above the topmost detected
table (pdfplumber misses rows whose top border is on the previous page), and
split them into: continuation of previous page's last row + full rows."""
import json
import re
import sys

import pdfplumber

pdf_path, out_path, first_page = sys.argv[1], sys.argv[2], int(sys.argv[3])
CODE = re.compile(r'^[A-ZАВСЕНКМОРТХ]\d\d[†*]?$')
res = {}
with pdfplumber.open(pdf_path) as pdf:
    for pno in range(first_page - 1, len(pdf.pages)):
        page = pdf.pages[pno]
        ts = sorted(page.find_tables(), key=lambda t: t.bbox[1])
        if ts:
            t = ts[0]
            cols = [c[0] for c in t.rows[0].cells if c]
            top = t.bbox[1]
            words = [w for w in page.extract_words() if w['bottom'] <= top + 1 and w['top'] > 30]
            if words and len(cols) == 6:
                lines = {}
                for w in words:
                    lines.setdefault(round(w['top']), []).append(w)
                groups = [[[] for _ in range(6)]]  # group 0 = continuation
                for key in sorted(lines):
                    lw = sorted(lines[key], key=lambda w: w['x0'])
                    first = lw[0]
                    if first['x0'] < cols[1] - 2 and CODE.match(first['text']):
                        groups.append([[] for _ in range(6)])
                    for w in lw:
                        idx = max(i for i, x in enumerate(cols) if w['x0'] >= x - 2)
                        groups[-1][idx].append(w['text'])
                res[pno + 1] = [[' '.join(c) for c in g] for g in groups]
            elif words:
                res[pno + 1] = {'cols': cols, 'words': [w['text'] for w in words]}
        page.flush_cache()
json.dump(res, open(out_path, 'w'), ensure_ascii=False)
print('pages with text above table', len(res))
