import assert from "node:assert/strict";
import {
  blockDivisionAutocompleteValue,
  blockExpenseAutocompleteValue,
  employeeAutocompleteValue,
  fillAdjustmentRow,
  premiumDetailKind,
  subBlockAutocompleteValue,
  vehicleAutocompleteValue,
  vehicleExpenseAutocompleteValue,
  shouldFillAutocompleteValue,
  shouldOpenNewRow,
  shouldFillHeaderField,
  shouldContinuePremiumInput,
  premiumDetailGroupKey,
  shouldContinuePremiumDetails,
  detailFormControlSelectors,
  employeeAutocompleteField,
  adcodeAutocompleteField,
  monthlyAllowanceDetailKindFromDomSnapshot,
  monthlyAllowanceInputMappings,
  blockDivisionAutocompleteField,
  subBlockAutocompleteField,
  blockExpenseAutocompleteField,
  shouldUseSingleRemainingAutocompleteFallback,
  singleRemainingAutocompleteOptionIndex,
  vehicleAutocompleteField,
  vehicleExpenseAutocompleteField
} from "./page-actions.js";
import { resolveCategory } from "../categories/registry.js";
import type { ManualAdjustmentRecord } from "../types.js";

function record(extra: Partial<ManualAdjustmentRecord>): ManualAdjustmentRecord {
  return {
    id: null,
    period_month: 4,
    period_year: 2026,
    emp_code: "B0065",
    gang_code: "B2N",
    division_code: "P1B",
    adjustment_type: "AUTO_BUFFER",
    adjustment_name: "AUTO SPSI",
    amount: 4000,
    remarks: "",
    category_key: "spsi",
    ...extra
  };
}

function fakePageForDescriptionOrder(options: {
  delayedSubblokReady?: boolean;
  domDetailKind?: "blok" | "kendaraan" | "";
  hiddenSelectMissKeys?: string[];
} = {}) {
  const values = new Map<string, string>();
  const fills: string[] = [];
  const clears: string[] = [];
  const keyPresses: string[] = [];
  const menuClicks: string[] = [];
  const networkIdleAfterFields: string[] = [];
  const waitForFunctionLabels: string[] = [];
  let lastSelectedField = "";
  let subblokReady = !options.delayedSubblokReady;
  const page = {
    waitForLoadState: async (state?: string) => {
      if (!state || state === "networkidle") {
        networkIdleAfterFields.push(lastSelectedField || "initial");
      }
    },
    waitForFunction: async (_fn: unknown, arg?: { key?: string }) => {
      waitForFunctionLabels.push(arg?.key ?? "unknown");
      if (arg?.key === "subblok") subblokReady = true;
    },
    waitForTimeout: async () => {},
    evaluate: async (_fn: unknown, field: { inputSelector: string; value: string; key?: string }) => {
      lastSelectedField = "key" in field ? String((field as { key: string }).key) : field.inputSelector;
      if (field.key === "subblok" && !subblokReady) return false;
      if (field.key && options.hiddenSelectMissKeys?.includes(field.key)) return false;
      values.set(field.inputSelector, field.value);
      return true;
    },
    locator: (selector: string) => {
      const optionField = selector.includes("ddlSubBlk") && selector.includes("option")
        ? "subblok"
        : selector.includes("ddlVehCode") && selector.includes("option")
          ? "vehicle"
          : selector.includes("ddlVehExpCode") && selector.includes("option")
            ? "vehicle_expense"
        : selector.includes("ddlExpCode") && selector.includes("option")
          ? "expense"
          : "";
      const locator = {
        first: () => locator,
        nth: () => locator,
        last: () => locator,
        waitFor: async () => {},
        isVisible: async () => {
          if (selector.includes("ddlSubBlk") || selector.includes("trSubBlkCode")) return options.domDetailKind === "blok";
          if (selector.includes("ddlVehCode") || selector.includes("trVehCode")) return options.domDetailKind === "kendaraan";
          return true;
        },
        inputValue: async () => values.get(selector) ?? "",
        fill: async (value: string) => {
          fills.push(`${selector}=${value}`);
          values.set(selector, value);
        },
        clear: async () => {
          clears.push(selector);
          values.set(selector, "");
        },
        press: async () => {},
        pressSequentially: async (value: string) => {
          keyPresses.push(`${selector}:${value}`);
          lastSelectedField = selector;
        },
        click: async () => {
          if (selector.includes(".ui-menu-item")) {
            menuClicks.push(selector);
            const fallbackValue = lastSelectedField.includes("ddlVeh")
              ? "T0020"
              : "PM0903B2";
            values.set(lastSelectedField, fallbackValue);
          }
          if (selector.includes("btnAdd")) lastSelectedField = "add";
        },
        selectOption: async (value: string) => {
          values.set(selector, value);
        },
        count: async () => {
          if (optionField === "subblok") {
            waitForFunctionLabels.push("subblok");
            if (!subblokReady) {
              subblokReady = true;
              return 0;
            }
            return 1;
          }
          if (optionField === "vehicle" || optionField === "vehicle_expense") {
            waitForFunctionLabels.push(optionField);
            return 1;
          }
          if (selector.includes(".ui-menu-item:visible")) return 1;
          if (optionField === "expense") {
            waitForFunctionLabels.push("expense");
            return 1;
          }
          return 0;
        },
        getAttribute: async () => optionField === "expense" ? "L" : optionField === "subblok" ? "PM0903B2" : optionField === "vehicle" ? "T0020" : "",
        textContent: async () => optionField === "expense" ? "L (LABOUR)" : optionField === "subblok" ? "PM0903B2" : optionField === "vehicle" ? "T0020" : "",
        evaluateAll: async () => [],
        evaluate: async (fn: (node: { querySelectorAll: (selector: string) => Array<{ id?: string; textContent?: string }> }) => unknown) => {
          if (!selector.includes("MainContent_MultiDimAcc_tbAccount")) return [];
          const ids = options.domDetailKind === "blok"
            ? ["MainContent_MultiDimAcc_ddlBlock", "MainContent_MultiDimAcc_ddlSubBlk", "MainContent_MultiDimAcc_ddlExpCode"]
            : options.domDetailKind === "kendaraan"
              ? ["MainContent_MultiDimAcc_ddlVehCode", "MainContent_MultiDimAcc_ddlVehExpCode"]
              : [];
          const labels = options.domDetailKind === "blok"
            ? ["Division Code", "Field No Code", "Expense Code"]
            : options.domDetailKind === "kendaraan"
              ? ["Vehicle Code", "Vehicle Expense Code"]
              : [];
          return fn({
            querySelectorAll: (query: string) => {
              if (query === "[id]") return ids.map((id) => ({ id }));
              return labels.map((textContent) => ({ textContent }));
            }
          });
        }
      };
      return locator;
    }
  };
  return { page, fills, clears, keyPresses, menuClicks, networkIdleAfterFields, waitForFunctionLabels };
}

assert.equal(
  employeeAutocompleteValue(record({ emp_code: "B0065", emp_name: "SURYANTI" })),
  "B0065"
);

assert.equal(
  employeeAutocompleteValue(record({ emp_code: "1902054607770001", emp_name: "SURYANTI" })),
  "SURYANTI"
);

assert.throws(
  () => employeeAutocompleteValue(record({ emp_code: "1902054607770001", emp_name: "1902054607770001" })),
  /Employee autocomplete would use NIK/
);

const blockRecord = record({
  adjustment_type: "PREMI",
  adjustment_name: "PREMI PRUNING",
  category_key: "premi",
  gang_code: "G1H",
  divisioncode: "G 1",
  detail_type: "blok",
  subblok: "P0901",
  subblok_raw: "P09/01",
  expense_code: "L"
});

assert.equal(premiumDetailKind(blockRecord), "blok");
assert.equal(blockDivisionAutocompleteValue(blockRecord), "G 1");
assert.equal(subBlockAutocompleteValue(blockRecord), "PM0901G1");
assert.equal(subBlockAutocompleteValue({ ...blockRecord, subblok: "P0801", subblok_raw: null }), "PM0801G1");
assert.equal(subBlockAutocompleteValue({ ...blockRecord, subblok: "PM0801", subblok_raw: null }), "PM0801G1");
assert.equal(blockExpenseAutocompleteValue(blockRecord), "L");
assert.equal(shouldFillAutocompleteValue("", "G0597"), true);
assert.equal(shouldFillAutocompleteValue("G0597 - ABDURRAHMAN", "G0597"), false);
assert.equal(shouldFillAutocompleteValue("PREMI PRUNING", "PREMI PRUNING"), false);
assert.equal(shouldFillAutocompleteValue("(AL) TUNJANGAN PREMI ((PM) PRUNING)", "(AL) TUNJANGAN PREMI ((PM) PRUNING)"), false);
assert.equal(shouldFillAutocompleteValue("PREMI BRONDOL", "PREMI PRUNING"), true);
assert.equal(shouldOpenNewRow(blockRecord, false, false), true);
assert.equal(shouldOpenNewRow(blockRecord, false, true), false);
assert.equal(shouldContinuePremiumInput(blockRecord, { continueEmployeePremium: true, continuePremiumDetails: false }), false);
assert.equal(shouldOpenNewRow(blockRecord, false, shouldContinuePremiumInput(blockRecord, { continueEmployeePremium: true, continuePremiumDetails: false })), true);
assert.equal(shouldContinuePremiumInput(blockRecord, { continueEmployeePremium: true, continuePremiumDetails: true }), true);
assert.equal(shouldOpenNewRow(blockRecord, false, shouldContinuePremiumInput(blockRecord, { continueEmployeePremium: true, continuePremiumDetails: true })), false);
assert.equal(shouldFillHeaderField("employee", true), false);
assert.equal(shouldFillHeaderField("adcode", true), true);
assert.equal(shouldFillHeaderField("employee", false), true);
assert.equal(shouldFillHeaderField("adcode", false), true);
assert.equal(shouldOpenNewRow(record({ adjustment_type: "AUTO_BUFFER", category_key: "spsi" }), false, false), true);
assert.equal(detailFormControlSelectors.empInput, "#MainContent_ddlEmployee + input.ui-autocomplete-input");
assert.equal(detailFormControlSelectors.adcodeInput, "#MainContent_ddlTaskCode + input.ui-autocomplete-input");
assert.deepEqual(employeeAutocompleteField(blockRecord), {
  key: "employee",
  selectSelector: "#MainContent_ddlEmployee",
  inputSelector: "#MainContent_ddlEmployee + input.ui-autocomplete-input",
  value: "B0065"
});
assert.deepEqual(adcodeAutocompleteField({ ...blockRecord, ad_code: "AL3PM0601", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) PRUNING)" }, resolveCategory(blockRecord, "premi")), {
  key: "adcode",
  selectSelector: "#MainContent_ddlTaskCode",
  inputSelector: "#MainContent_ddlTaskCode + input.ui-autocomplete-input",
  value: "(AL) TUNJANGAN PREMI ((PM) PRUNING)"
});
const pruningCategory = resolveCategory({ ...blockRecord, ad_code: "AL3PM0601", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) PRUNING)" }, "premi");
const firstPruningDetail = { ...blockRecord, emp_code: "G0597", ad_code: "AL3PM0601", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) PRUNING)", subblok: "P0801", amount: 120000 };
const secondPruningDetail = { ...firstPruningDetail, subblok: "P0802", amount: 90000, transaction_index: 2 };
const rakingDetail = { ...firstPruningDetail, adjustment_name: "PREMI RAKING", ad_code: "AL3PM0106", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) WEEDING - CIRCLE RAKING)", subblok: "P0901", amount: 70000 };
const otherEmployeePruningDetail = { ...firstPruningDetail, emp_code: "G0601", subblok: "P0803", amount: 80000 };
assert.equal(
  premiumDetailGroupKey(firstPruningDetail, pruningCategory),
  "G0597|P1B|PREMI PRUNING|(AL) TUNJANGAN PREMI ((PM) PRUNING)"
);
assert.equal(shouldContinuePremiumDetails(firstPruningDetail, secondPruningDetail, pruningCategory, pruningCategory), true);
assert.equal(shouldContinuePremiumDetails(firstPruningDetail, rakingDetail, pruningCategory, resolveCategory(rakingDetail, "premi")), false);
assert.equal(shouldContinuePremiumDetails(firstPruningDetail, otherEmployeePruningDetail, pruningCategory, pruningCategory), false);
assert.deepEqual(blockDivisionAutocompleteField(blockRecord), {
  key: "block",
  selectSelector: "#MainContent_MultiDimAcc_ddlBlock",
  inputSelector: "#MainContent_MultiDimAcc_ddlBlock + input.ui-autocomplete-input",
  value: "G1",
  waitForNetworkIdle: false
});
assert.deepEqual(subBlockAutocompleteField(blockRecord), {
  key: "subblok",
  selectSelector: "#MainContent_MultiDimAcc_ddlSubBlk",
  inputSelector: "#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input",
  value: "PM0901G1",
  waitForNetworkIdle: false
});
assert.deepEqual(blockExpenseAutocompleteField(blockRecord), {
  key: "expense",
  selectSelector: "#MainContent_MultiDimAcc_ddlExpCode",
  inputSelector: "#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input",
  value: "L",
  waitForNetworkIdle: false
});
assert.deepEqual(monthlyAllowanceInputMappings.subblok.metadataAliases, ["subblok", "sub_blok", "sub_block", "fieldcode", "field_code"]);
assert.equal(monthlyAllowanceInputMappings.subblok.selectSelector, "#MainContent_MultiDimAcc_ddlSubBlk");
assert.equal(monthlyAllowanceInputMappings.vehicle.metadataAliases.includes("nomor_kendaraan"), true);
assert.equal(monthlyAllowanceInputMappings.vehicle.selectSelector, "#MainContent_MultiDimAcc_ddlVehCode");
assert.equal(
  monthlyAllowanceDetailKindFromDomSnapshot(["MainContent_MultiDimAcc_ddlSubBlk"], ["Field No Code"]),
  "blok"
);
assert.equal(
  monthlyAllowanceDetailKindFromDomSnapshot(["MainContent_MultiDimAcc_ddlVehCode"], ["Vehicle Code"]),
  "kendaraan"
);
assert.equal(monthlyAllowanceDetailKindFromDomSnapshot(["MainContent_txtAmount"], ["Amount"]), "");
assert.throws(
  () => {
    const category = resolveCategory({ ...blockRecord, ad_code: "" }, "premi");
    category.adcode({ ...blockRecord, ad_code: "" });
  },
  /missing ad_code/
);

const vehicleRecord = record({
  adjustment_type: "PREMI",
  adjustment_name: "PREMI DRIVER",
  category_key: "premi",
  detail_type: "kendaraan",
  vehicle_code: "BE003",
  vehicle_expense_code: "11"
});

assert.equal(premiumDetailKind(vehicleRecord), "kendaraan");
assert.equal(vehicleAutocompleteValue(vehicleRecord), "BE003");
assert.equal(vehicleExpenseAutocompleteValue(vehicleRecord), "11");
assert.equal(vehicleExpenseAutocompleteValue({ ...vehicleRecord, vehicle_expense_code: "", expense_code: "driver" }), "DRIVER");

const grossDeductionRecord = record({
  adjustment_type: "POTONGAN_KOTOR",
  adjustment_name: "KOREKSI PANEN",
  category_key: "potongan_upah_kotor",
  detail_type: "",
  subblok: "",
  subblok_raw: "",
  vehicle_code: "",
  expense_code: "L"
});

assert.equal(premiumDetailKind(grossDeductionRecord), "");
assert.equal(premiumDetailKind({ ...grossDeductionRecord, subblok: "P0903", subblok_raw: "P09/03" }), "blok");
assert.equal(premiumDetailKind({ ...grossDeductionRecord, vehicle_code: "T0020" }), "kendaraan");
assert.equal(blockDivisionAutocompleteValue(grossDeductionRecord), "B 2");
assert.throws(
  () => subBlockAutocompleteValue(grossDeductionRecord),
  /Sub block is required for block-based adjustment row/
);

const {
  page: missingMetadataBlockPage,
  keyPresses: missingMetadataBlockKeyPresses,
  menuClicks: missingMetadataBlockMenuClicks
} = fakePageForDescriptionOrder({ domDetailKind: "blok" });
await fillAdjustmentRow(
  missingMetadataBlockPage as never,
  grossDeductionRecord,
  resolveCategory(grossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(
  missingMetadataBlockKeyPresses.includes("#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input: "),
  true
);
assert.equal(missingMetadataBlockMenuClicks.includes(".ui-menu-item:visible"), true);

const {
  page: missingMetadataVehiclePage,
  keyPresses: missingMetadataVehicleKeyPresses,
  menuClicks: missingMetadataVehicleMenuClicks
} = fakePageForDescriptionOrder({ domDetailKind: "kendaraan" });
await fillAdjustmentRow(
  missingMetadataVehiclePage as never,
  grossDeductionRecord,
  resolveCategory(grossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(
  missingMetadataVehicleKeyPresses.includes("#MainContent_MultiDimAcc_ddlVehCode + input.ui-autocomplete-input: "),
  true
);
assert.equal(missingMetadataVehicleMenuClicks.includes(".ui-menu-item:visible"), true);

const {
  page: descriptionOrderPage,
  fills: descriptionOrderFills,
  keyPresses: descriptionOrderKeyPresses
} = fakePageForDescriptionOrder();
const missingSubblockGrossDeductionRecord = { ...grossDeductionRecord, detail_type: "blok" };
await fillAdjustmentRow(
  descriptionOrderPage as never,
  missingSubblockGrossDeductionRecord,
  resolveCategory(missingSubblockGrossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(descriptionOrderFills[0], "#MainContent_txtDocDesc=KOREKSI PANEN");
assert.equal(
  descriptionOrderKeyPresses.includes("#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input: "),
  true
);

const {
  page: blockWaitPage,
  networkIdleAfterFields: blockNetworkIdleAfterFields
} = fakePageForDescriptionOrder();
const completeGrossDeductionRecord = {
  ...grossDeductionRecord,
  subblok: "P0903",
  subblok_raw: "P09/03",
  vehicle_code: ""
};
await fillAdjustmentRow(
  blockWaitPage as never,
  completeGrossDeductionRecord,
  resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(blockNetworkIdleAfterFields.includes("block"), false);
assert.equal(blockNetworkIdleAfterFields.includes("subblok"), false);
assert.equal(blockNetworkIdleAfterFields.includes("expense"), false);

const {
  page: delayedSubblokPage,
  waitForFunctionLabels: delayedSubblokWaits
} = fakePageForDescriptionOrder({ delayedSubblokReady: true });
await fillAdjustmentRow(
  delayedSubblokPage as never,
  completeGrossDeductionRecord,
  resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.deepEqual([...new Set(delayedSubblokWaits)], ["subblok", "expense"]);
const {
  page: subblokNoSearchResultPage,
  clears: subblokNoSearchResultClears,
  keyPresses: subblokNoSearchResultKeyPresses,
  menuClicks: subblokNoSearchResultMenuClicks
} = fakePageForDescriptionOrder({ hiddenSelectMissKeys: ["subblok"] });
await fillAdjustmentRow(
  subblokNoSearchResultPage as never,
  completeGrossDeductionRecord,
  resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(
  subblokNoSearchResultKeyPresses.includes("#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input: "),
  true
);
assert.equal(
  subblokNoSearchResultClears.includes("#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input"),
  true
);
assert.equal(subblokNoSearchResultMenuClicks.includes(".ui-menu-item:visible"), true);

const {
  page: blockDivisionNoSearchResultPage,
  keyPresses: blockDivisionNoSearchResultKeyPresses
} = fakePageForDescriptionOrder({ hiddenSelectMissKeys: ["block"] });
await fillAdjustmentRow(
  blockDivisionNoSearchResultPage as never,
  completeGrossDeductionRecord,
  resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(
  blockDivisionNoSearchResultKeyPresses.includes("#MainContent_MultiDimAcc_ddlBlock + input.ui-autocomplete-input: "),
  true
);

const noMatchExpenseRecord = { ...completeGrossDeductionRecord, expense_code: "BAD" };
const {
  page: expenseNoSearchResultPage,
  keyPresses: expenseNoSearchResultKeyPresses
} = fakePageForDescriptionOrder();
await fillAdjustmentRow(
  expenseNoSearchResultPage as never,
  noMatchExpenseRecord,
  resolveCategory(noMatchExpenseRecord, "potongan_upah_kotor"),
  true,
  "P1B"
);
assert.equal(
  expenseNoSearchResultKeyPresses.includes("#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input: "),
  true
);

const {
  page: adcodeNoSearchResultPage,
  keyPresses: adcodeNoSearchResultKeyPresses
} = fakePageForDescriptionOrder({ hiddenSelectMissKeys: ["adcode"] });
await assert.rejects(
  () => fillAdjustmentRow(
    adcodeNoSearchResultPage as never,
    completeGrossDeductionRecord,
    resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
    true,
    "P1B"
  ),
  /No autocomplete option matched adcode/
);
assert.equal(
  adcodeNoSearchResultKeyPresses.includes("#MainContent_ddlTaskCode + input.ui-autocomplete-input: "),
  false
);

const {
  page: employeeNoSearchResultPage,
  keyPresses: employeeNoSearchResultKeyPresses
} = fakePageForDescriptionOrder({ hiddenSelectMissKeys: ["employee"] });
await assert.rejects(
  () => fillAdjustmentRow(
    employeeNoSearchResultPage as never,
    completeGrossDeductionRecord,
    resolveCategory(completeGrossDeductionRecord, "potongan_upah_kotor"),
    true,
    "P1B"
  ),
  /No autocomplete option matched employee/
);
assert.equal(
  employeeNoSearchResultKeyPresses.includes("#MainContent_ddlEmployee + input.ui-autocomplete-input: "),
  false
);

assert.equal(shouldUseSingleRemainingAutocompleteFallback(subBlockAutocompleteField(blockRecord)), true);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(vehicleAutocompleteField(vehicleRecord)), true);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(blockExpenseAutocompleteField(blockRecord)), false);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(vehicleExpenseAutocompleteField(vehicleRecord)), false);
assert.equal(singleRemainingAutocompleteOptionIndex(["PM0901G1 (P09/01)"]), 0);
assert.equal(singleRemainingAutocompleteOptionIndex(["PM0901G1", "PM0901G2"]), null);
assert.equal(singleRemainingAutocompleteOptionIndex([]), null);
