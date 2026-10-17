#!/usr/bin/env python3
"""forms-watch: інструменти для релізів СКЗ ДПС (спеціалізоване клієнтське ПЗ).

Пакет СКЗ — єдине місце, де ДПС публікує контрольні XSD усіх форм:
https://tax.gov.ua/elektronna-zvitnist/spetsializovane-klientske-program/

Підкоманди (лише stdlib + зовнішній `7z` для `diff`):

  check SNAPSHOT        Порівняти знімок сторінки (JSON від docs/forms-watch/skz_page.js)
                        з baseline у docs/forms-watch/state.json; показати, які
                        форми з переліку змін зачіпають НАШІ XSD/генератори.
  diff ARCHIVE          Розпакувати завантажений архів СКЗ (zip -> NSIS edzv-*.exe ->
                        7z x -> xsd/) і звірити його XSD з вендореними в репозиторії.
                        ARCHIVE може бути .zip, .exe або вже розпакованою текою.
  update-state SNAPSHOT Записати реліз зі знімка в state.json (робить людина /
                        Claude Code після опрацювання, не агент — див. Крок 7).

Ключ відповідності форм: «родина» = код без літери типу платника і без версії,
тобто символи [1:6] коду (J1300205 -> 13002, версія 05). J і F однієї родини
мають спільну структуру, тож зміна F-версії теж сигнал для J-генератора.

Запуск (архів з tax.gov.ua — недовірені дані; скрипт тримати окремо від нього):
  python3 -I docs/tools/forms_watch/skz.py diff ~/Downloads/719211.zip
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATE = REPO / 'docs' / 'forms-watch' / 'state.json'
CODE_RE = re.compile(r'(?<![A-Z0-9])([JF])(\d{7})(?!\d)')
CODE_SCAN_SKIP = {'.git', 'docs', 'node_modules', '__pycache__', 'static', 'i18n'}


def family(code):
    return code[1:6]


def version(code):
    return int(code[6:8])


# ---------------------------------------------------------------- repo discovery

def vendored_xsds(repo=REPO):
    """{form code: [path, ...]} — XSD, що лежать у модулях (зазвичай tests/schemas/)."""
    out = {}
    for p in sorted(repo.rglob('*.xsd')):
        if any(part in CODE_SCAN_SKIP for part in p.relative_to(repo).parts):
            continue
        m = CODE_RE.fullmatch(p.stem)
        if m:
            out.setdefault(p.stem, []).append(p)
    return out


def referenced_codes(repo=REPO):
    """{form code: {"модуль/підтека", ...}} — коди форм, що згадуються в .py/.xml модулів."""
    out = {}
    for p in repo.rglob('*'):
        if p.suffix not in ('.py', '.xml') or not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in CODE_SCAN_SKIP for part in rel.parts) or len(rel.parts) < 2:
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for m in CODE_RE.finditer(text):
            # «модуль/підтека»: models/wizard = генератор, data = лише довідник типів документів
            where = '/'.join(rel.parts[:2]) if len(rel.parts) > 2 else rel.parts[0]
            out.setdefault(m.group(0), set()).add(where)
    return out


def our_families(repo=REPO):
    """{family: {'codes': {code: {modules}}, 'xsd': {code: [paths]}}}"""
    fams = {}
    for code, mods in referenced_codes(repo).items():
        fams.setdefault(family(code), {'codes': {}, 'xsd': {}})['codes'][code] = mods
    for code, paths in vendored_xsds(repo).items():
        f = fams.setdefault(family(code), {'codes': {}, 'xsd': {}})
        f['xsd'][code] = paths
        f['codes'].setdefault(code, set()).add('/'.join(paths[0].relative_to(repo).parts[:2]))
    return fams


def match_forms(forms, fams):
    """Рядки «форма з релізу -> наша родина» з оцінкою, що саме змінилось."""
    hits = []
    for code in sorted(forms):
        fam = fams.get(family(code))
        if not fam:
            continue
        ours = sorted(fam['codes'])
        max_ver = max(version(c) for c in ours)
        if code in fam['codes']:
            kind = 'та сама версія (схему перевидано)'
        elif version(code) > max_ver:
            kind = 'НОВА ВЕРСІЯ (у нас до v%02d)' % max_ver
        else:
            kind = 'інша/старша версія'
        mods = sorted(set().union(*fam['codes'].values()))
        hits.append({'form': code, 'kind': kind, 'ours': ours, 'modules': mods,
                     'vendored_xsd': sorted(fam['xsd'])})
    return hits


# ---------------------------------------------------------------- check

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def cmd_check(args):
    snap = load_json(args.snapshot)
    state = load_json(args.state)
    upd, full = snap.get('update') or {}, snap.get('full') or {}
    if not upd.get('version'):
        print('ПОМИЛКА: у знімку немає update.version — верстка сторінки змінилась? '
              'Звір skz_page.js з HTML сторінки.', file=sys.stderr)
        return 2
    def vt(v):
        return tuple(int(x) for x in (v or '0').split('.'))
    new_update = vt(upd['version']) > vt(state.get('skz_version'))
    new_full = vt(full.get('version')) > vt(state.get('skz_full_version'))
    same_ver_new_file = (not new_update and upd.get('zip', {}).get('url')
                         and upd['zip']['url'] != state.get('skz_update_file'))
    print('СКЗ baseline: оновлення %s від %s, повна %s від %s' % (
        state.get('skz_version'), state.get('skz_dated'),
        state.get('skz_full_version'), state.get('skz_full_dated')))
    print('СКЗ на сторінці: оновлення %s від %s (%s, %s байт), повна %s від %s' % (
        upd['version'], upd.get('dated'), upd.get('zip', {}).get('url'),
        upd.get('zip', {}).get('bytes'), full.get('version'), full.get('dated')))
    status = 'NEW_RELEASE' if (new_update or new_full) else (
        'REPUBLISHED' if same_ver_new_file else 'NO_CHANGE')
    print('STATUS:', status)
    if new_full:
        print('Нова ПОВНА версія — після опрацювання онови skz_full_* (update-state).')
    if same_ver_new_file:
        print('Та сама версія, але інший файл — ДПС перевидала архів; звір вручну (diff).')
    if status == 'NO_CHANGE' and not args.all:
        return 0
    forms = (upd.get('changelog') or {}).get('forms') or []
    old, new = vt(state.get('skz_version')), vt(upd['version'])
    gap = len(old) < 3 or len(new) < 3 or old[:2] != new[:2] or new[2] - old[2] > 1
    if new_update and gap:
        print('УВАГА: пропущено проміжні релізи (%s -> %s). Перелік змін на сторінці — лише '
              'для останнього; повний набір змін — тільки через `diff` накопичувального '
              'архіву оновлення.' % (state.get('skz_version'), upd['version']))
    prev = set(state.get('skz_forms_added') or [])
    print('Форм у переліку змін: %d (нових відносно baseline: %d)' % (
        len(forms), len(set(forms) - prev)))
    hits = match_forms(forms, our_families(Path(args.repo)))
    if not hits:
        print('Наших форм (родин) у переліку змін немає.')
    for h in hits:
        print('  %s: %s; наші: %s; модулі: %s; вендорені XSD: %s' % (
            h['form'], h['kind'], ', '.join(h['ours']), ', '.join(h['modules']),
            ', '.join(h['vendored_xsd']) or '—'))
    if args.json:
        print(json.dumps({'status': status, 'hits': hits}, ensure_ascii=False))
    return 0


def cmd_update_state(args):
    snap = load_json(args.snapshot)
    state = load_json(args.state)
    upd, full = snap['update'], snap.get('full') or {}
    cl = upd.get('changelog') or {}
    state.update({
        'skz_page': snap.get('page'),
        'skz_version': upd['version'],
        'skz_dated': upd.get('dated'),
        'skz_update_file': upd.get('zip', {}).get('url'),
        'skz_update_bytes': upd.get('zip', {}).get('bytes'),
        'skz_update_last_modified': upd.get('zip', {}).get('last_modified'),
        'skz_changelog_file': cl.get('url'),
        'skz_forms_added': cl.get('forms', []),
        'skz_full_version': full.get('version'),
        'skz_full_dated': full.get('dated'),
        'skz_full_file': full.get('zip', {}).get('url'),
        'skz_full_bytes': full.get('zip', {}).get('bytes'),
        'skz_captured_at': snap.get('captured_at'),
    })
    with open(args.state, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('state.json: СКЗ %s від %s' % (upd['version'], upd.get('dated')))
    return 0


# ---------------------------------------------------------------- diff

def _7z():
    exe = shutil.which('7z') or shutil.which('7za') or shutil.which('7zz')
    if not exe:
        sys.exit('Потрібен 7-Zip (`sudo apt install 7zip` / p7zip-full) — NSIS .exe '
                 'розпаковує лише він.')
    return exe


def _safe_unzip(src, dest):
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep):
                raise SystemExit('Небезпечний шлях в архіві: %r' % info.filename)
        z.extractall(dest)


def unpack(archive, work):
    """zip -> *.exe (NSIS) -> 7z x. Повертає теку з розпакованим вмістом."""
    archive = Path(archive)
    if archive.is_dir():
        return archive
    work.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        _safe_unzip(archive, work / 'zip')
        exes = sorted((work / 'zip').rglob('*.exe'))
    elif archive.suffix.lower() == '.exe':
        exes = [archive]
    else:
        raise SystemExit('Невідомий формат: %s' % archive)
    for i, exe in enumerate(exes):
        out = work / ('exe%d_%s' % (i, exe.stem))
        print('7z x %s' % exe.name, file=sys.stderr)
        subprocess.run([_7z(), 'x', '-y', '-bso0', '-bsp0', '-o%s' % out, str(exe)], check=True)
    return work


def archive_xsds(root):
    """{form code: path} — XSD форм з розпакованого архіву (+ common_types)."""
    out = {}
    for p in sorted(Path(root).rglob('*.xsd')):
        key = p.stem if CODE_RE.fullmatch(p.stem) else p.name.lower()
        # кілька однойменних (оновлення поверх повної) — беремо той, що в теці xsd/
        if key not in out or 'xsd' in [x.lower() for x in p.parent.parts]:
            out[key] = p
    return out


def _cp1251(path):
    return path.read_bytes().decode('cp1251', errors='replace').splitlines()


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_diff(args):
    repo = Path(args.repo)
    tmp = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix='skz_'))
    try:
        root = unpack(args.archive, tmp)
        arc = archive_xsds(root)
        forms_in_arc = {k for k in arc if CODE_RE.fullmatch(k)}
        print('XSD в архіві: %d (форм: %d)' % (len(arc), len(forms_in_arc)))
        if not arc:
            print('XSD не знайдено — перевір структуру архіву (--keep DIR і подивись).')
            return 2
        ours = vendored_xsds(repo)
        changed = []
        print('\n== Вендорені XSD проти архіву ==')
        common = sorted({p for paths in ours.values() for p in paths}
                        | set(repo.rglob('common_types.xsd')))
        for p in common:
            if any(part in CODE_SCAN_SKIP for part in p.relative_to(repo).parts):
                continue
            key = p.stem if CODE_RE.fullmatch(p.stem) else p.name.lower()
            rel = p.relative_to(repo)
            a = arc.get(key)
            if a is None:
                print('  %-16s немає в архіві (для оновлення = не змінювався)  (%s)' % (key, rel))
                continue
            if _sha(a) == _sha(p):
                print('  %-16s без змін  (%s)' % (key, rel))
                continue
            d = list(difflib.unified_diff(_cp1251(p), _cp1251(a), str(rel), 'СКЗ/' + a.name,
                                          lineterm='', n=1))
            plus = sum(1 for x in d if x.startswith('+') and not x.startswith('+++'))
            minus = sum(1 for x in d if x.startswith('-') and not x.startswith('---'))
            print('  %-16s ЗМІНЕНО +%d/-%d  (%s)' % (key, plus, minus, rel))
            changed.append(key)
            if args.show_diff:
                print('\n'.join('      ' + x for x in d[:args.show_diff]))
        print('\n== Новіші версії наших родин в архіві ==')
        fams = our_families(repo)
        newer = []
        for code in sorted(forms_in_arc):
            fam = fams.get(family(code))
            if fam and code not in fam['codes'] and \
                    version(code) > max(version(c) for c in fam['codes']):
                newer.append(code)
                print('  %s  (наші: %s; модулі: %s)' % (
                    code, ', '.join(sorted(fam['codes'])),
                    ', '.join(sorted(set().union(*fam['codes'].values())))))
        if not newer:
            print('  —')
        print('\nCHANGED_FORMS: %s' % ' '.join(sorted(set(changed) | set(newer))))
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repo', default=str(REPO), help='корінь репозиторію l10n_ua')
    ap.add_argument('--state', default=str(STATE), help='docs/forms-watch/state.json')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check', help='знімок сторінки СКЗ проти baseline')
    c.add_argument('snapshot')
    c.add_argument('--all', action='store_true', help='зіставити форми навіть без нового релізу')
    c.add_argument('--json', action='store_true', help='додатково вивести JSON-рядок')
    c.set_defaults(func=cmd_check)
    u = sub.add_parser('update-state', help='записати реліз зі знімка в state.json')
    u.add_argument('snapshot')
    u.set_defaults(func=cmd_update_state)
    d = sub.add_parser('diff', help='звірити XSD завантаженого архіву з вендореними')
    d.add_argument('archive', help='.zip з tax.gov.ua, edzv-*.exe або розпакована тека')
    d.add_argument('--keep', metavar='DIR', help='розпакувати в DIR і не видаляти')
    d.add_argument('--show-diff', type=int, default=0, metavar='N',
                   help='показати перші N рядків unified diff для змінених XSD')
    d.set_defaults(func=cmd_diff)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
