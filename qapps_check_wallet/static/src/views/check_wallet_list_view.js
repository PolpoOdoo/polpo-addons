/** @odoo-module */

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { CheckWalletListController } from "./check_wallet_list_controller";

export const checkWalletListView = {
    ...listView,
    Controller: CheckWalletListController,
};

registry.category("views").add("qapps_check_wallet_list", checkWalletListView);
