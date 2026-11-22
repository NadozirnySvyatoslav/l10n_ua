import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const cogMenuRegistry = registry.category("cogMenu");

/**
 * The print entry under the cog of the material report.
 *
 * The standard report binding only shows up in the cog that appears next to
 * the counter of selected rows, that is, it requires ticking them first. What
 * people want to print is what is already on screen, so the entry is added to
 * the permanent cog and the current search domain is sent to the server. It
 * carries both the control panel filters and the narrowing done with the
 * left-hand panel, so the paper repeats the screen.
 */
export class MaterialReportPrintMenu extends Component {
    static template = "l10n_ua_stock_forms.MaterialReportPrintMenu";
    static components = { DropdownItem };
    setup() {
        this.action = useService("action");
    }

    async onPrint() {
        const { domain, resModel } = this.env.searchModel;
        // orm is taken from env on purpose rather than through useService:
        // selecting the item closes the dropdown, destroying this component
        // before the answer arrives, and after destruction useService("orm")
        // substitutes the result with a promise that never resolves
        // (_protectMethod in web/core/utils/hooks.js). The call then reaches
        // the server but doAction never happens — printing silently does
        // nothing. The action service has no such tie to the component's life,
        // so the doAction below is safe.
        const action = await this.env.services.orm.call(
            resModel,
            "action_print_report",
            [domain]
        );
        return this.action.doAction(action);
    }
}

cogMenuRegistry.add(
    "l10n_ua_material_report_print",
    {
        Component: MaterialReportPrintMenu,
        groupNumber: 1,
        isDisplayed: ({ config, searchModel }) =>
            searchModel?.resModel === "l10n_ua.material.report.line" &&
            ["list", "pivot"].includes(config.viewType),
    },
    { sequence: 1 }
);
