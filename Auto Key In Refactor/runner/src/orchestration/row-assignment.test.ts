import assert from "node:assert/strict";
import { assignRowsToTabs, duplicateInputRowKeys, employeeAssignmentGroupKey, findCrossTabEmployeeSplits } from "./row-assignment.js";
import type { ManualAdjustmentRecord } from "../types.js";

function record(extra: Partial<ManualAdjustmentRecord>): ManualAdjustmentRecord {
  return {
    id: null,
    period_month: 4,
    period_year: 2026,
    emp_code: "G0597",
    gang_code: "G1H",
    division_code: "AB1",
    adjustment_type: "PREMI",
    adjustment_name: "PREMI PRUNING",
    amount: 100000,
    remarks: "",
    category_key: "premi",
    ad_code: "AL3PM0601",
    ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) PRUNING)",
    detail_type: "blok",
    subblok: "P0801",
    ...extra
  };
}

const rows = [
  record({ emp_code: "G0597", subblok: "P0801", amount: 100000, transaction_index: 1 }),
  record({ emp_code: "G0597", subblok: "P0802", amount: 90000, transaction_index: 2 }),
  record({
    emp_code: "G0597",
    adjustment_name: "PREMI RAKING",
    ad_code: "AL3PM0701",
    ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) RAKING)",
    subblok: "P0803",
    amount: 70000,
    transaction_index: 3
  }),
  record({ emp_code: "G0601", subblok: "P0901", amount: 50000, transaction_index: 1 }),
  record({ emp_code: "G0601", subblok: "P0902", amount: 40000, transaction_index: 2 }),
  record({
    emp_code: "G0700",
    adjustment_type: "AUTO_BUFFER",
    adjustment_name: "AUTO SPSI",
    category_key: "spsi",
    ad_code: null,
    ad_code_desc: null,
    detail_type: null,
    subblok: null,
    amount: 4000
  })
];

const assigned = assignRowsToTabs(rows, 2, "premi");
assert.equal(assigned.length, 2);
assert.deepEqual(assigned[0].map((row) => `${row.emp_code}:${row.subblok ?? row.adjustment_name}`), [
  "G0597:P0801",
  "G0597:P0802",
  "G0597:P0803",
  "G0700:AUTO SPSI"
]);
assert.deepEqual(assigned[1].map((row) => `${row.emp_code}:${row.subblok ?? row.adjustment_name}`), [
  "G0601:P0901",
  "G0601:P0902"
]);
assert.equal(employeeAssignmentGroupKey(record({ emp_code: "G0597", estate: "AB1" }), "premi"), "G0597|AB1");

const interleavedRows = [
  record({ emp_code: "G0597", subblok: "P0801", amount: 100000 }),
  record({ emp_code: "G0601", subblok: "P0901", amount: 50000 }),
  record({ emp_code: "G0597", subblok: "P0802", amount: 90000 }),
  record({ emp_code: "G0601", subblok: "P0902", amount: 40000 }),
  record({ emp_code: "G0610", subblok: "P1001", amount: 30000 })
];
const employeeAssigned = assignRowsToTabs(interleavedRows, 2, "premi");
assert.deepEqual(employeeAssigned[0].map((row) => `${row.emp_code}:${row.subblok}`), [
  "G0597:P0801",
  "G0597:P0802",
  "G0610:P1001"
]);
assert.deepEqual(employeeAssigned[1].map((row) => `${row.emp_code}:${row.subblok}`), [
  "G0601:P0901",
  "G0601:P0902"
]);

const potonganRows = [
  record({ emp_code: "B0001", adjustment_type: "POTONGAN_BERSIH", adjustment_name: "POTONGAN PINJAMAN", category_key: "potongan_upah_bersih", detail_key: "pinjaman-1" }),
  record({ emp_code: "B0002", adjustment_type: "POTONGAN_BERSIH", adjustment_name: "POTONGAN PINJAMAN", category_key: "potongan_upah_bersih", detail_key: "pinjaman-2" }),
  record({ emp_code: "B0001", adjustment_type: "POTONGAN_BERSIH", adjustment_name: "POTONGAN LAIN", category_key: "potongan_upah_bersih", detail_key: "lain-1" })
];
const assignedPotongan = assignRowsToTabs(potonganRows, 2, "potongan_upah_bersih");
const tabsWithB0001 = assignedPotongan.filter((tabRows) => tabRows.some((row) => row.emp_code === "B0001"));
assert.equal(tabsWithB0001.length, 1);
assert.deepEqual(tabsWithB0001[0].map((row) => row.detail_key), ["pinjaman-1", "lain-1"]);

const mixedPremiumRows = [
  record({ emp_code: "G0597", adjustment_name: "PREMI PRUNING", category_key: "premi", detail_key: "pruning-1" }),
  record({ emp_code: "G0601", adjustment_name: "PREMI TBS", category_key: "premi", detail_key: "tbs-1" }),
  record({ emp_code: "G0597", adjustment_name: "TUNJANGAN PREMI", category_key: "premi_tunjangan", detail_key: "tunjangan-1" }),
];
const assignedMixedPremium = assignRowsToTabs(mixedPremiumRows, 3, "premi");
const mixedPremiumTabsWithG0597 = assignedMixedPremium.filter((tabRows) => tabRows.some((row) => row.emp_code === "G0597"));
assert.equal(mixedPremiumTabsWithG0597.length, 1);
assert.deepEqual(mixedPremiumTabsWithG0597[0].map((row) => row.detail_key), ["pruning-1", "tunjangan-1"]);
assert.deepEqual(findCrossTabEmployeeSplits(assignedMixedPremium, "premi"), []);

const duplicateRows = [
  record({ emp_code: "G0597", detail_key: "duplicate-detail", amount: 100000 }),
  record({ emp_code: "G0601", detail_key: "unique-detail", amount: 120000 }),
  record({ emp_code: "G0597", detail_key: "duplicate-detail", amount: 100000 })
];
assert.deepEqual(duplicateInputRowKeys(duplicateRows, "premi"), ["duplicate-detail"]);
