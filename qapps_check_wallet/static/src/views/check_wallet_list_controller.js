/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { onWillStart, useState } from "@odoo/owl";

const STATE_FILTER_NAMES = [
    "filter_pending",
    "filter_in_deposit",
    "filter_deposited",
    "filter_at_collection",
    "filter_overdue",
    "filter_to_expire",
];

export class CheckWalletListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dashboard = useState({
            loaded: false,
            pending_amount: 0,
            pending_count: 0,
            deposited_amount: 0,
            deposited_count: 0,
            at_collection_amount: 0,
            at_collection_count: 0,
            overdue_amount: 0,
            overdue_count: 0,
            total_count: 0,
            currency_id: false,
        });
        onWillStart(this.loadDashboard.bind(this));
    }

    async loadDashboard() {
        const totals = await this.orm.call("qapps.check.wallet", "get_dashboard_totals", []);
        Object.assign(this.dashboard, totals, { loaded: true });
    }

    formatAmount(amount) {
        if (!this.dashboard.currency_id) {
            return amount;
        }
        return formatMonetary(amount, { currencyId: this.dashboard.currency_id });
    }

    onCardClick(filterName) {
        const searchModel = this.env.searchModel;
        const items = Object.values(searchModel.searchItems);

        for (const item of items) {
            if (
                item.type === "filter" &&
                STATE_FILTER_NAMES.includes(item.name) &&
                item.name !== filterName
            ) {
                const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
                if (isActive) {
                    searchModel.toggleSearchItem(item.id);
                }
            }
        }

        const target = items.find(
            (item) => item.type === "filter" && item.name === filterName
        );
        if (target) {
            const isTargetActive = searchModel.query.some(
                (q) => q.searchItemId === target.id
            );
            if (!isTargetActive) {
                searchModel.toggleSearchItem(target.id);
            }
        }
    }
}

CheckWalletListController.template = "qapps_check_wallet.CheckWalletListView";
