import assert from "node:assert/strict";
import { buildVehicleExperimentPayload, filterVehicleTransactions } from "./vehicle-p1b-b1t-runner.js";

const transactions = [
  {
    emp_code: "B0001",
    emp_name: "DRIVER A",
    gang_code: "B1T",
    estate: "P1B",
    estate_code: "P1B",
    division_code: "B 1",
    adjustment_type: "PREMI",
    adjustment_name: "PREMI ANGKUT",
    amount: 125000,
    detail_type: "kendaraan",
    nomor_kendaraan: "DT001",
    vehicle_expense_code: "L",
    ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) TRANSPORT)"
  },
  {
    emp_code: "B0002",
    gang_code: "B1T",
    estate: "P1B",
    estate_code: "P1B",
    division_code: "B 1",
    adjustment_type: "PREMI",
    adjustment_name: "PREMI BLOK",
    amount: 100000,
    detail_type: "blok",
    subblok: "P0801"
  },
  {
    emp_code: "B0003",
    gang_code: "B2T",
    estate: "P1B",
    estate_code: "P1B",
    division_code: "B 2",
    adjustment_type: "PREMI",
    adjustment_name: "PREMI ANGKUT",
    amount: 90000,
    detail_type: "kendaraan",
    vehicle_code: "DT002"
  }
];

const filtered = filterVehicleTransactions(transactions, { divisionCode: "P1B", gangCode: "B1T" });
assert.equal(filtered.length, 1);
assert.equal(filtered[0].nomor_kendaraan, "DT001");

const payload = buildVehicleExperimentPayload(filtered, { month: 4, year: 2026, divisionCode: "P1B", gangCode: "B1T", execute: false });
assert.equal(payload.division_code, "P1B");
assert.equal(payload.gang_code, "B1T");
assert.equal(payload.category_key, "premi");
assert.equal(payload.runner_mode, "dry_run");
assert.equal(payload.records.length, 1);
assert.equal(payload.records[0].detail_type, "kendaraan");
assert.equal(payload.records[0].vehicle_code, "DT001");
assert.equal(payload.records[0].vehicle_expense_code, "L");
