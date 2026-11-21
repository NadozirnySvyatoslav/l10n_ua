#!/usr/bin/env python3
"""Decide which modules the clickbot CI job has to cover (issue #635).

Prints one of:

* ``all``  -- click every app with repository menus (the clickbot tooling
  itself changed, no base to diff against, or explicitly requested);
* ``none`` -- nothing the clickbot addon installs was changed: skip the job;
* a comma-separated list of changed modules installed by
  ``l10n_ua_clickbot_test`` (the test then also clicks the apps of the
  modules depending on them).

and writes ``modules=<value>`` to $GITHUB_OUTPUT when it is set.

Usage: select_modules.py [--base REF] [--modules LIST]
"""
import argparse
import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON = os.path.join(ROOT, 'tools', 'clickbot', 'l10n_ua_clickbot_test')
# Changes under these paths re-run the clickbot on every app.
TOOLING = ('tools/clickbot/', '.github/workflows/clickbot.yml')


def manifest(path):
    with open(os.path.join(path, '__manifest__.py'), encoding='utf-8') as f:
        return ast.literal_eval(f.read())


def repo_modules():
    return {
        d for d in os.listdir(ROOT)
        if os.path.isfile(os.path.join(ROOT, d, '__manifest__.py'))
    }


def installed_closure():
    """Repository modules installed together with the clickbot addon."""
    repo = repo_modules()
    todo = [d for d in manifest(ADDON)['depends'] if d in repo]
    seen = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(d for d in manifest(os.path.join(ROOT, name)).get('depends', []) if d in repo)
    return seen


def changed_paths(base):
    out = subprocess.run(
        ['git', 'diff', '--name-only', '%s...HEAD' % base],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    return [p for p in out.splitlines() if p]


def select(base=None, modules=None):
    if modules:
        return modules
    if not base:
        return 'all'
    paths = changed_paths(base)
    if any(p.startswith(TOOLING) for p in paths):
        return 'all'
    changed = {p.split('/', 1)[0] for p in paths if '/' in p} & installed_closure()
    return ','.join(sorted(changed)) or 'none'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--base', help='git ref to diff against (e.g. origin/20.0)')
    parser.add_argument('--modules', help='explicit comma-separated list or "all"')
    args = parser.parse_args()
    value = select(args.base, (args.modules or '').replace(' ', ''))
    print(value)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write('modules=%s\n' % value)


if __name__ == '__main__':
    sys.exit(main())
