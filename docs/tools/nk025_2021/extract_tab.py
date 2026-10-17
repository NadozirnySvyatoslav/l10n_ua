"""Extract the tabular list (section 6) of NK 025:2021 PDF into raw rows JSON."""
import json
import sys

import pdfplumber

pdf_path, out_path, first_page = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = []
with pdfplumber.open(pdf_path) as pdf:
    for pno in range(first_page - 1, len(pdf.pages)):
        page = pdf.pages[pno]
        for table in page.extract_tables():
            for row in table:
                cells = [(c or '').strip() for c in row]
                rows.append({'page': pno + 1, 'cells': cells})
        page.flush_cache()
        if pno % 100 == 0:
            print(pno + 1, len(rows), file=sys.stderr, flush=True)
json.dump(rows, open(out_path, 'w'), ensure_ascii=False)
print('rows', len(rows))
