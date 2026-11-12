#!/usr/bin/env python3
"""Check that every `#: code:` reference in i18n .po/.pot files has a line number.

Odoo loads translations with `int(line_number)` (odoo/tools/translate.py); a
reference like `#: code:addons/m/models/x.py` without `:0` makes the whole
language load fail with `ValueError: invalid literal for int()` (issue #558).

Usage: python3 docs/tools/po_check/check_po_refs.py [repo_root]
Exit code 1 if any broken reference is found.
"""
import pathlib
import re
import sys

CODE_REF = re.compile(r'^code:\S+:\d+$')


def check_file(path):
    errors = []
    with open(path, encoding='utf-8') as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.startswith('#: '):
                continue
            for ref in line[3:].split():
                if ref.startswith('code:') and not CODE_REF.match(ref):
                    errors.append(f'{path}:{lineno}: ERROR no line number in "{ref}" (add ":0")')
    return errors


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    files = sorted(p for p in root.glob('*/i18n/*.po*') if p.suffix in ('.po', '.pot'))
    errors = []
    for path in files:
        errors.extend(check_file(path))
    for err in errors:
        print(err)
    print(f'checked {len(files)} files, {len(errors)} errors')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
