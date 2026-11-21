"""Clickbot over the apps that hold l10n_ua menus (issue #635).

Odoo's own ``click_all`` tests (web/tests/test_click_everywhere.py) click
every installed app in one test and stop at the first error.  Here every app
that contains a menu of a repository module is a separate subTest, run as
admin and as demo, so one broken app does not hide the others, and known
false positives are listed in EXCEPTIONS instead of failing the run.

Run (see .github/workflows/clickbot.yml):

    odoo server -d <db> --test-enable --test-tags click_l10n_ua --stop-after-init

Environment:

* ``L10N_UA_CLICKBOT_MODULES`` -- comma-separated changed modules; only apps
  holding menus of these modules or of modules depending on them are
  clicked.  Empty or ``all``: every app with repository menus.
* ``L10N_UA_CLICKBOT_TIMEOUT`` -- seconds per app and user (default 900).
* ``L10N_UA_CLICKBOT_REPORT`` -- path of a JSON file to write the per-app
  results to (default: none).
"""
import json
import logging
import os
import time
import unittest

from requests import PreparedRequest, Response, Session

from odoo.modules.module import get_module_path
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo

_logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
THIS_MODULE = 'l10n_ua_clickbot_test'

# Menu xmlid -> (kind, reason).  Kinds:
#   rows_not_openable -- the list rows carry ``cursor-pointer`` (which the
#       clickbot takes for "openable") but are report lines that are not
#       meant to open a form; errors raised on this menu are tolerated.
#   core_race -- a race in core Odoo, the result is not deterministic and
#       the error may be reported on the next menu; the menu is not clicked.
#   opens_modal -- core list whose rows open a dialog instead of a form: the
#       clickbot cannot go back, the dialog stays open and every following
#       menu of the app fails ("Component is destroyed", timeouts on "New");
#       the menu is not clicked.
EXCEPTIONS = {
    'l10n_ua_stock_forms.menu_material_report': (
        'rows_not_openable', "M-19 material report: rows are report lines, intentionally not openable"),
    'account.menu_action_account_moves_all': (
        'rows_not_openable', "core Journal Items: grouped report list, rows do not open a form"),
    'hr_timesheet.menu_hr_activity_analysis': (
        'rows_not_openable', "core Timesheets report by employee: report list"),
    'hr_timesheet.timesheet_menu_report_timesheet_by_project': (
        'rows_not_openable', "core Timesheets report by project: report list"),
    'hr_timesheet.timesheet_menu_report_timesheet_by_task': (
        'rows_not_openable', "core Timesheets report by task: report list"),
    'hr_skills.hr_certification_menu': (
        'opens_modal', "core Certifications (hr_skills): rows call open_hr_employee_skill_modal"),
    'hr_skills.menu_learnings_training_attendances': (
        'core_race', "core race in Training Attendances (hr_skills)"),
}
SKIPPED_KINDS = {'core_race', 'opens_modal'}

DONE_SIGNAL = 'l10n_ua clickbot done'

# Wraps startClickEverywhere: menus of SKIPPED_KINDS are pruned from the menu
# tree the clickbot walks; console errors are collected (errors of tolerated
# menus are only logged) and reported as one console.error at the end, so a
# single run lists every broken menu of the app instead of the first one.
CLICKBOT_JS = """
(async () => {
    const XMLID = %(xmlid)s;
    const SKIP = new Set(%(skip)s);
    const TOLERATE = new Set(%(tolerate)s);
    const DONE = %(done)s;
    const FAILURE_SIGNAL = "clickbot test failed";
    const MENU_RE = /Current testing menu is .* \\(([\\w.]+)\\)/;
    const format = (args) => args.map((arg) => {
        if (arg instanceof Error) {
            return arg.stack || arg.message;
        }
        if (typeof arg === "string") {
            return arg;
        }
        try {
            return JSON.stringify(arg);
        } catch {
            return String(arg);
        }
    }).join(" ");

    while (!odoo.__WOWL_DEBUG__?.root?.env) {
        await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const menuService = odoo.__WOWL_DEBUG__.root.env.services.menu;
    const getMenuAsTree = menuService.getMenuAsTree;
    const prune = (node) => ({
        ...node,
        childrenTree: (node.childrenTree || []).filter((child) => !SKIP.has(child.xmlid)).map(prune),
    });
    menuService.getMenuAsTree = function (menuId) {
        return prune(getMenuAsTree.call(this, menuId));
    };

    const unexpected = [];
    const tolerated = new Set();
    const consoleError = console.error;
    console.error = (...args) => {
        const message = format(args);
        if (message === FAILURE_SIGNAL) {
            return;  // decided below from the collected errors
        }
        const match = message.match(MENU_RE);
        if (match && TOLERATE.has(match[1])) {
            tolerated.add(match[1]);
            console.warn(`l10n_ua clickbot: tolerated error on ${match[1]} (EXCEPTIONS)\\n${message}`);
            return;
        }
        unexpected.push(message);
        console.warn(`l10n_ua clickbot: error\\n${message}`);
    };
    try {
        await odoo.loader.modules.get("@web/webclient/clickbot/clickbot_loader")
            .startClickEverywhere({ xmlId: XMLID, logger: true });
    } catch (error) {
        unexpected.push(format([error]));
    } finally {
        console.error = consoleError;
        menuService.getMenuAsTree = getMenuAsTree;
    }
    if (tolerated.size) {
        console.log(`l10n_ua clickbot: tolerated menus: ${[...tolerated].join(", ")}`);
    }
    if (unexpected.length) {
        console.error(`l10n_ua clickbot: ${unexpected.length} error(s) in ${XMLID}:\\n\\n${unexpected.join("\\n\\n")}`);
    } else {
        console.log(DONE);
    }
})();
"""


def _is_repo_module(name):
    path = get_module_path(name, display_warning=False)
    return bool(path) and os.path.realpath(path).startswith(os.path.realpath(REPO_ROOT) + os.sep)


@tagged('click_l10n_ua', '-standard', 'post_install', '-at_install')
class TestClickL10nUa(HttpCaseWithUserDemo):

    results = []

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        # same odoofin mock as web/tests/test_click_everywhere.py
        if 'proxy/v2/get_dashboard_institutions' in r.url:
            r = Response()
            r.status_code = 200
            r.json = list
            return r
        return super()._request_handler(s, r, **kw)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        users = cls.env.ref('base.user_admin') | cls.user_demo
        if 'tour_enabled' in users._fields:
            users.tour_enabled = False
        cls.timeout = int(os.environ.get('L10N_UA_CLICKBOT_TIMEOUT') or 900)
        cls.target_modules = cls._target_modules()
        _logger.info("clickbot: modules whose apps are clicked: %s", ', '.join(sorted(cls.target_modules)))

    @classmethod
    def tearDownClass(cls):
        report = os.environ.get('L10N_UA_CLICKBOT_REPORT')
        if report:
            with open(report, 'w', encoding='utf-8') as f:
                json.dump(cls.results, f, ensure_ascii=False, indent=1)
        super().tearDownClass()

    @classmethod
    def _target_modules(cls):
        Module = cls.env['ir.module.module']
        own = {
            name for name in Module.search([('state', '=', 'installed')]).mapped('name')
            if name != THIS_MODULE and _is_repo_module(name)
        }
        selected = [m.strip() for m in (os.environ.get('L10N_UA_CLICKBOT_MODULES') or '').split(',') if m.strip()]
        if not selected or selected == ['all']:
            return own
        changed = Module.search([('name', 'in', selected), ('state', '=', 'installed')])
        return own & set((changed | changed.downstream_dependencies()).mapped('name'))

    def _apps(self, user):
        """(name, xmlid) of the root menus visible to ``user`` that hold a
        menu of one of the target modules."""
        menus = self.env['ir.ui.menu'].with_user(user).load_menus(False)

        def xmlids(menu_id):
            menu = menus[menu_id]
            yield menu.get('xmlid') or ''
            for child in menu.get('children') or ():
                yield from xmlids(child)

        apps = []
        for app_id in menus['root']['children']:
            if any(x.split('.')[0] in self.target_modules for x in xmlids(app_id) if x):
                apps.append((menus[app_id]['name'], menus[app_id]['xmlid']))
        return apps

    def _click_apps(self, login, user):
        apps = self._apps(user)
        if not apps:
            self.skipTest("no app with l10n_ua menus to click for %s" % login)
        skip = sorted(x for x, (kind, _reason) in EXCEPTIONS.items() if kind in SKIPPED_KINDS)
        tolerate = sorted(x for x, (kind, _reason) in EXCEPTIONS.items() if kind not in SKIPPED_KINDS)
        for name, xmlid in apps:
            with self.subTest(app=xmlid, login=login):
                _logger.info("clickbot: testing app %s (%s) as %s", name, xmlid, login)
                code = CLICKBOT_JS % {
                    'xmlid': json.dumps(xmlid),
                    'skip': json.dumps(skip),
                    'tolerate': json.dumps(tolerate),
                    'done': json.dumps(DONE_SIGNAL),
                }
                start = time.time()
                result = {'app': xmlid, 'name': name, 'login': login}
                try:
                    self.browser_js(
                        '/odoo', code, 'odoo.isReady === true', login=login,
                        timeout=self.timeout, success_signal=DONE_SIGNAL,
                    )
                except unittest.SkipTest as e:
                    # e.g. Chrome or websocket-client missing: not a pass
                    result.update(ok=False, skipped=True, error=str(e))
                    raise
                except BaseException as e:
                    result.update(ok=False, error=str(e)[:20000])
                    raise
                else:
                    result['ok'] = True
                finally:
                    result['seconds'] = round(time.time() - start)
                    self.results.append(result)
                    _logger.info("clickbot: %s as %s: %s in %ss", xmlid, login,
                                 'ok' if result.get('ok') else 'SKIPPED' if result.get('skipped') else 'FAILED',
                                 result['seconds'])

    def test_01_click_as_admin(self):
        self._click_apps('admin', self.env.ref('base.user_admin'))

    def test_02_click_as_demo(self):
        self._click_apps('demo', self.user_demo)
