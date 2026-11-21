#!/usr/bin/env python3
"""Turn clickbot-report.json into the job summary and failed-apps.txt.

Exits 1 when an app run failed or was skipped (a skipped run -- Chrome or
websocket-client missing -- must not look like a pass), or when there is
no report at all although apps had to be clicked.

Usage: report.py <out_dir>   (appends Markdown to $GITHUB_STEP_SUMMARY)
"""
import json
import os
import sys


def main(out):
    path = os.path.join(out, 'clickbot-report.json')
    lines = []
    if not os.path.exists(path):
        lines.append('### Clickbot\n\nNo report: the test did not run to the end, see odoo-clickbot.log.')
        rc = 1
    else:
        with open(path, encoding='utf-8') as f:
            rows = json.load(f)
        bad = [r for r in rows if not r.get('ok')]
        lines.append('### Clickbot: %d app runs, %d not ok\n' % (len(rows), len(bad)))
        if rows:
            lines.append('| app | user | result | s |\n|---|---|---|---|')
        for r in rows:
            status = 'ok' if r.get('ok') else '**skipped**' if r.get('skipped') else '**FAILED**'
            lines.append('| %s (`%s`) | %s | %s | %s |' % (r['name'], r['app'], r['login'], status, r['seconds']))
        with open(os.path.join(out, 'failed-apps.txt'), 'w', encoding='utf-8') as f:
            for r in bad:
                f.write('%s as %s\n%s\n\n' % (r['app'], r['login'], r.get('error', '')))
        rc = 1 if bad else 0
    text = '\n'.join(lines) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
