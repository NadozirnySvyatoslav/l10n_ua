#!/usr/bin/env python3
"""Check module pages for the Odoo Apps store.

Error (exit 1): static/description/index.html with non-ASCII text but no
<meta charset="UTF-8"> — Odoo Apps reads such a file as Latin-1 and the
Ukrainian text turns into "ÐÐ¾Ð³Ð¾…" (10.11.2026: 13 modules broken).
Warnings: no index.html, no icon.png.

Usage: python3 docs/tools/apps_check/check_descriptions.py [repo_root] [module ...]
"""
import os
import re
import sys

CHARSET_RE = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?utf-8', re.I)


def check(root, modules=None):
    errors, warnings = [], []
    names = modules or sorted(
        d for d in os.listdir(root)
        if os.path.isfile(os.path.join(root, d, '__manifest__.py')))
    for name in names:
        desc = os.path.join(root, name, 'static', 'description')
        index = os.path.join(desc, 'index.html')
        if os.path.isfile(index):
            data = open(index, 'rb').read()
            if any(b > 127 for b in data) and not CHARSET_RE.search(data[:1024]):
                errors.append('%s: index.html без <meta charset="UTF-8"> на початку файлу '
                              '(Apps покаже кракозябри)' % name)
        else:
            warnings.append('%s: немає static/description/index.html' % name)
        if not os.path.isfile(os.path.join(desc, 'icon.png')):
            warnings.append('%s: немає static/description/icon.png' % name)
    return errors, warnings


def main():
    args = sys.argv[1:]
    root = args.pop(0) if args and os.path.isdir(args[0]) and not os.path.isfile(
        os.path.join(args[0], '__manifest__.py')) else '.'
    errors, warnings = check(root, args or None)
    for w in warnings:
        print('WARN  ' + w)
    for e in errors:
        print('ERROR ' + e)
    print('%d помилок, %d попереджень' % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
