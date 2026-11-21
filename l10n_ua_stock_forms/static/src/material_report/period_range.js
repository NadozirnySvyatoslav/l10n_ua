import { Component, onWillDestroy, onWillStart, proxy, status, t, useProps } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { RPCError } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const WIZARD_MODEL = "l10n_ua.material.report.wizard";

// How long the button stays lit after a recomputation. The standard loading
// indicator only appears after 250 ms (web/webclient/loading_indicator), while
// recomputing a period fits into tens of milliseconds, so it never flashes on
// its own: the numbers simply become different, which reads as "nothing
// happened". The highlight delays neither the request nor the display of the
// rows — it merely leaves a trace that the report really was refreshed.
const APPLIED_HIGHLIGHT_MS = 1200;

/**
 * Props of the component for a view controller.
 *
 * It lives here rather than next to the controllers because List and Pivot
 * travel in different bundles: Odoo keeps the pivot in
 * `web.assets_backend_lazy`, so shared code must sit in a module both can see.
 */
export function materialReportPeriodProps(controller, reload) {
    return {
        // The report being read, taken from `active_id` — the key the URL keeps
        // over a reload, so the button is still there after a Back from a
        // drilled-down list (see the action record for the whole story).
        wizardId: controller.props.context?.active_id || false,
        onPeriodChanged: reload,
    };
}

/**
 * The material report period in the control panel — a button carrying the applied
 * range, which opens a small dialog to change it.
 *
 * The period is not a filter here: the opening balance is all the movement up
 * to the "from" date, so changing a date does not narrow the displayed rows
 * but makes the server recompute the report. That is why the dialog writes the
 * dates onto the wizard and the view is reloaded afterwards, instead of
 * touching the search domain.
 *
 * The dialog is a plain form with the standard `daterange` widget rather than
 * a calendar of our own. Two ordinary date fields cannot collapse into a
 * single day by a stray click, and a form footer is the confirmation everyone
 * already knows — the custom popover needed a hand-made Apply button because
 * DateTimePicker hides its footer for plain dates.
 *
 * The dates are read from the wizard rather than from the action context: the
 * context is fixed at the moment the report opens and, after the very first
 * change of period, would show a stale value when switching List ↔ Pivot.
 */
export class MaterialReportPeriodRange extends Component {
    static template = "l10n_ua_stock_forms.MaterialReportPeriodRange";
    props = useProps({
        wizardId: t.or([t.number(), t.boolean()]).optional(),
        onPeriodChanged: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            available: false,
            value: [false, false],
            pending: false,
            justApplied: false,
        });
        this.highlightTimer = null;
        onWillDestroy(() => browser.clearTimeout(this.highlightTimer));

        onWillStart(() => this.loadPeriod());
    }

    async loadPeriod() {
        if (!this.props.wizardId) {
            return;
        }
        // searchRead and not read: a report can be out of reach in two ways,
        // and read answers both with an error dialog rather than an answer.
        // It is transient, so a vacuum may have taken it (MissingError); and it
        // belongs to one company, so selecting another in the switcher puts it
        // behind a record rule (AccessError). A search simply comes back empty,
        // which is what the two cases have in common.
        const records = await this.orm.searchRead(
            WIZARD_MODEL,
            [["id", "=", this.props.wizardId]],
            ["date_from", "date_to"]
        );
        if (!records.length) {
            return this.rebuild();
        }
        this.state.available = true;
        this.state.value = [
            deserializeDate(records[0].date_from),
            deserializeDate(records[0].date_to),
        ];
    }

    /**
     * The report on screen is out of reach — build the one that belongs here.
     *
     * Without this the reader is left with an empty grid and no period button,
     * and nothing on screen to say why. It happens after changing company in
     * the switcher: the URL brings back the report that was open (its id is all
     * the URL carries), and that report belongs to the company left behind.
     * What is wanted then is plainly the same report for the company now in
     * force — the very thing the menu builds. The other way in is a vacuumed
     * report, where rebuilding is just as right.
     *
     * This component is where it happens because this is what reads the report
     * back and therefore what finds out that it is gone.
     *
     * A refusal from the server is left where it is. The company in force may
     * have no warehouse, and then there is no report to build — but nobody
     * asked for one here, so an error dialog would appear out of nowhere. The
     * screen simply stays as it is, and the menu says what is wrong when it is
     * clicked on purpose. Only a business refusal is swallowed; anything else
     * is a fault of ours and goes on being reported.
     */
    async rebuild() {
        let action;
        try {
            action = await this.orm.call(
                WIZARD_MODEL,
                "action_open_default_report",
                []
            );
        } catch (error) {
            if (error instanceof RPCError) {
                return;
            }
            throw error;
        }
        return this.action.doAction(action);
    }

    /** The period the report currently shows — the button's caption. */
    get label() {
        const [dateFrom, dateTo] = this.state.value;
        return `${formatDate(dateFrom)} — ${formatDate(dateTo)}`;
    }

    async onOpen() {
        const action = await this.orm.call(WIZARD_MODEL, "action_open_period", [
            [this.props.wizardId],
        ]);
        await this.action.doAction(action, {
            onClose: () => this.onApplied(),
        });
    }

    /**
     * The dialog is gone; what it wrote has to be picked up.
     *
     * `onClose` fires on Cancel too, so the period is re-read rather than
     * assumed: that keeps the button honest whichever way the dialog was left,
     * and re-reading one record is cheaper than getting the caption wrong.
     */
    async onApplied() {
        // onClose also fires when the dialog goes away because the user left
        // the report (a menu click): the button is destroyed by then, and its
        // services refuse to be called ("Component is destroyed").
        if (status(this) === "destroyed") {
            return;
        }
        this.state.pending = true;
        try {
            await this.loadPeriod();
        } finally {
            this.state.pending = false;
        }
        if (status(this) === "destroyed") {
            return;
        }
        await this.props.onPeriodChanged();
        this.highlight();
    }

    /** A trace that the report really was recomputed: see APPLIED_HIGHLIGHT_MS. */
    highlight() {
        browser.clearTimeout(this.highlightTimer);
        this.state.justApplied = true;
        this.highlightTimer = browser.setTimeout(() => {
            this.state.justApplied = false;
        }, APPLIED_HIGHLIGHT_MS);
    }
}
