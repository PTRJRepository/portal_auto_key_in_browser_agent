import assert from "node:assert/strict";
import {
  blockDivisionAutocompleteValue,
  blockExpenseAutocompleteValue,
  employeeAutocompleteValue,
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
  value: "G1"
});
assert.deepEqual(subBlockAutocompleteField(blockRecord), {
  key: "subblok",
  selectSelector: "#MainContent_MultiDimAcc_ddlSubBlk",
  inputSelector: "#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input",
  value: "PM0901G1"
});
assert.deepEqual(blockExpenseAutocompleteField(blockRecord), {
  key: "expense",
  selectSelector: "#MainContent_MultiDimAcc_ddlExpCode",
  inputSelector: "#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input",
  value: "L"
});
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
assert.equal(shouldUseSingleRemainingAutocompleteFallback(subBlockAutocompleteField(blockRecord)), true);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(vehicleAutocompleteField(vehicleRecord)), true);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(blockExpenseAutocompleteField(blockRecord)), false);
assert.equal(shouldUseSingleRemainingAutocompleteFallback(vehicleExpenseAutocompleteField(vehicleRecord)), false);
assert.equal(singleRemainingAutocompleteOptionIndex(["PM0901G1 (P09/01)"]), 0);
assert.equal(singleRemainingAutocompleteOptionIndex(["PM0901G1", "PM0901G2"]), null);
assert.equal(singleRemainingAutocompleteOptionIndex([]), null);
