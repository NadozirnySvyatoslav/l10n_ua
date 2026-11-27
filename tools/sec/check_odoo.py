#!/usr/bin/env python3
"""Перевірки безпеки Odoo, яких не вміє semgrep. Код повернення 1 = збірка червона.

1. ACL (ir.model.access*.csv): запис/створення/видалення для portal, public або без групи.
   Виняток — рядок у .security-exceptions.txt:  <id запису ACL> -- причина
2. Record rules (XML): правило для portal/public, домен якого нічого не обмежує —
   [(1,'=',1)] (будь-які лапки), [], порожній або відсутній domain_force. Порядок атрибутів
   <record> не важливий. Виняток — те саме, за xml id правила.
3. sudo() у контролерах auth='public'/'none' або з auth не-літералом (змінна, **kwargs —
   вважаємо публічним; константу модуля AUTH = '...' розпізнаємо) без маркера на тому ж
   або попередньому рядку:
       # sudo-ok: причина
   Те саме для обхідних форм суперкористувача: with_user(SUPERUSER_ID|1), env(su=True),
   with_env(... su=True), api.Environment(cr, SUPERUSER_ID, ...).
4. nosemgrep / коротка форма nosem без пояснення (" -- причина").

Запуск:
  python3 tools/sec/check_odoo.py <корінь>               — повний аудит (щотижневий огляд)
  python3 tools/sec/check_odoo.py <корінь> --diff <BASE>  — лише рядки, додані/змінені
                                                            між BASE і HEAD (CI на PR)
У режимі --diff спрацювання в старому коді не валять PR: їх розбирає щотижневий аудит.
"""
import argparse
import ast
import csv
import pathlib
import re
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("root", nargs="?", default=".")
ap.add_argument("--diff", metavar="BASE", help="перевіряти лише зміни BASE..HEAD")
args = ap.parse_args()

ROOT = pathlib.Path(args.root).resolve()
SKIP = {".git", "node_modules", "__pycache__"}
RISKY_GROUPS = {"", "base.group_portal", "base.group_public", "group_portal", "group_public"}
EXC_FILE = ".security-exceptions.txt"
errors = []  # (шлях відносно ROOT, перший рядок, останній рядок, текст)


def changed_lines(base):
    """{шлях: множина номерів рядків у HEAD, доданих або змінених відносно base}."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "-U0", "--no-color", "--no-ext-diff", base, "HEAD"],
        check=True, capture_output=True, text=True).stdout
    result, cur = {}, None
    for line in out.splitlines():
        if line.startswith("+++ "):
            cur = None if line == "+++ /dev/null" else line[6:]  # "+++ b/шлях"
            if cur is not None:
                result.setdefault(cur, set())
        elif line.startswith("@@") and cur is not None:
            m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
            start, count = int(m.group(1)), int(m.group(2) or 1)
            result[cur].update(range(start, start + count))
    return result


CHANGED = changed_lines(args.diff) if args.diff else None


def files(pattern):
    for p in ROOT.rglob(pattern):
        if SKIP.intersection(p.relative_to(ROOT).parts):
            continue
        if CHANGED is not None and rel(p) not in CHANGED:
            continue
        yield p


def rel(p):
    return p.relative_to(ROOT).as_posix()


def report(path, first, last, msg):
    errors.append((path, first, last, msg))


def load_exceptions():
    ex = {}
    f = ROOT / EXC_FILE
    if f.exists():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, reason = line.partition(" -- ")
            if not reason.strip():
                report(EXC_FILE, n, n, "виняток без причини")
            ex[key.strip()] = reason.strip()
    return ex


EXC = load_exceptions()


def check_acl():
    for p in files("ir.model.access*.csv"):
        with p.open(encoding="utf-8") as fh:
            for n, row in enumerate(csv.DictReader(fh), 2):
                group = (row.get("group_id:id") or row.get("group_id/id") or "").strip()
                if group not in RISKY_GROUPS:
                    continue
                perms = [k for k in ("perm_write", "perm_create", "perm_unlink") if (row.get(k) or "").strip() == "1"]
                rid = (row.get("id") or "").strip()
                if perms and rid not in EXC:
                    who = group or "усі користувачі (група порожня)"
                    report(rel(p), n, n, f"{rid}: {','.join(perms)} для {who}")


# Атрибути <record> — у будь-якому порядку і з будь-якими лапками.
RECORD_RE = re.compile(r"<record\b([^>]*)>(.*?)</record>", re.S)
ATTR_RE = re.compile(r"""\b([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
DOMAIN_RE = re.compile(r"""<field\b[^>]*\bname\s*=\s*["']domain_force["'][^>]*?(?:/>|>(.*?)</field>)""", re.S)
EVAL_RE = re.compile(r"""\beval\s*=\s*(?:"([^"]*)"|'([^']*)')""")
# Домен, що нічого не обмежує: [] або [(N, '=', N)] з будь-якими лапками.
OPEN_DOMAIN_RE = re.compile(r"""^\[\s*(?:\(\s*(\d+)\s*,\s*["']=["']\s*,\s*\1\s*\)\s*,?\s*)?\]$""")


def _attrs(s):
    return {m.group(1): m.group(2) if m.group(2) is not None else m.group(3) for m in ATTR_RE.finditer(s)}


def _open_domain(body):
    """True, якщо domain_force правила не обмежує записів (немає, порожній, [], [(1,'=',1)])."""
    m = DOMAIN_RE.search(body)
    if not m:
        return True  # правило без domain_force — доступ до всіх записів
    tag = m.group(0)[:m.group(0).find(">") + 1]
    ev = EVAL_RE.search(tag)
    value = (ev.group(1) if ev and ev.group(1) is not None else ev.group(2)) if ev else (m.group(1) or "")
    value = value.strip()
    return not value or bool(OPEN_DOMAIN_RE.match(value))


def check_rules():
    for p in files("*.xml"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in RECORD_RE.finditer(text):
            attrs = _attrs(m.group(1))
            if attrs.get("model") != "ir.rule":
                continue
            rid = attrs.get("id", "?")
            body = m.group(2)
            if re.search(r"group_(portal|public)", body) and _open_domain(body):
                if rid not in EXC:
                    first = text.count("\n", 0, m.start()) + 1
                    last = text.count("\n", 0, m.end()) + 1
                    report(rel(p), first, last, f"правило {rid} відкриває всі записи portal/public")


def module_consts(tree):
    """{ім'я: рядок} для простих присвоєнь рівня модуля (AUTH = 'public')."""
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value
    return consts


def route_auth(fn, consts):
    """auth маршруту: літерал або константа модуля; будь-що інше — 'dynamic' (вважаємо ризиковим)."""
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and getattr(d.func, "attr", getattr(d.func, "id", "")) == "route":
            for kw in d.keywords:
                if kw.arg is None:
                    return "dynamic"  # **kwargs — auth може прийти звідти
                if kw.arg == "auth":
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        return kw.value.value
                    if isinstance(kw.value, ast.Name) and kw.value.id in consts:
                        return consts[kw.value.id]
                    return "dynamic"
            return "user"
    return None


MARK = re.compile(r"#\s*sudo-ok:\s*\S")
# semgrep приймає і повну форму маркера (nosemgrep), і коротку (nosem), регістр не важливий.
NOSEM = re.compile(r"#\s*nosem(?:grep)?\b(.*)", re.I)
SUPERUSER_NAMES = {"SUPERUSER_ID"}


def _is_superuser(node):
    """SUPERUSER_ID, odoo.SUPERUSER_ID, api.SUPERUSER_ID або літерал 1."""
    if isinstance(node, ast.Name):
        return node.id in SUPERUSER_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in SUPERUSER_NAMES
    return isinstance(node, ast.Constant) and node.value == 1 and not isinstance(node.value, bool)


def superuser_call(node):
    """Назва форми, якщо виклик піднімає права до суперкористувача, інакше None."""
    if not isinstance(node, ast.Call):
        return None
    name = getattr(node.func, "attr", getattr(node.func, "id", ""))
    if name == "sudo":
        # sudo(False) права не піднімає
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value is False:
            return None
        return "sudo()"
    for kw in node.keywords:
        if kw.arg == "su" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
            return f"{name or 'env'}(su=...)"
    if name == "with_user" and node.args and _is_superuser(node.args[0]):
        return "with_user(SUPERUSER_ID)"
    for kw in node.keywords:
        if kw.arg in ("user", "uid") and _is_superuser(kw.value):
            return f"{name}({kw.arg}=SUPERUSER_ID)"
    if name == "Environment" and len(node.args) > 1 and _is_superuser(node.args[1]):
        return "Environment(cr, SUPERUSER_ID)"
    if name == "Environment" and len(node.args) > 3 and not (
            isinstance(node.args[3], ast.Constant) and node.args[3].value is False):
        return "Environment(..., su)"
    return None


def check_sudo_and_nosemgrep():
    for p in files("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        lines = src.splitlines()
        for n, line in enumerate(lines, 1):
            m = NOSEM.search(line)
            if m and " -- " not in m.group(1):
                report(rel(p), n, n, "nosemgrep/nosem без пояснення (' -- причина')")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            report(rel(p), e.lineno or 1, e.lineno or 1, f"не парситься ({e.msg})")
            continue
        consts = module_consts(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            auth = route_auth(fn, consts)
            if auth not in ("public", "none", "dynamic"):
                continue
            # Зміна декоратора (напр. auth='user' -> 'public') теж робить старий sudo() новим ризиком.
            deco_first = min(d.lineno for d in fn.decorator_list)
            deco_last = max(d.end_lineno for d in fn.decorator_list)
            for node in ast.walk(fn):
                form = superuser_call(node)
                if form:
                    ln = node.lineno
                    near = lines[ln - 1] + "\n" + (lines[ln - 2] if ln > 1 else "")
                    if MARK.search(near):
                        continue
                    msg = f"{form} у маршруті auth='{auth}' ({fn.name}) без '# sudo-ok: причина'"
                    report(rel(p), ln, ln, msg)
                    report(rel(p), deco_first, deco_last, msg + f" [декоратор, sudo на рядку {ln}]")


check_acl()
check_rules()
check_sudo_and_nosemgrep()

if CHANGED is not None:
    errors = [e for e in errors if CHANGED.get(e[0], set()).intersection(range(e[1], e[2] + 1))]
    # одне спрацювання на sudo(): якщо змінено і рядок, і декоратор — лишаємо рядок sudo()
    seen, uniq = set(), []
    for e in errors:
        m = re.search(r"\[декоратор, sudo на рядку (\d+)\]", e[3])
        key = (e[0], int(m.group(1)) if m else e[1], e[3].split(" [декоратор")[0])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    errors = uniq
else:
    errors = [e for e in errors if "[декоратор" not in e[3]]

if errors:
    print("Перевірка безпеки не пройдена:")
    for path, first, _last, msg in errors:
        print(f"  - {path}:{first}: {msg}")
    sys.exit(1)
print("check_odoo: ок" + (f" (зміни від {args.diff})" if args.diff else " (повний аудит)"))
