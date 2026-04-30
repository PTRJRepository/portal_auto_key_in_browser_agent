import assert from "node:assert/strict";
import { resolveCategory } from "./registry.js";
import type { ManualAdjustmentRecord } from "../types.js";

function record(category_key: string, adjustment_name: string, remarks: string, extra: Partial<ManualAdjustmentRecord> = {}): ManualAdjustmentRecord {
  return {
    id: null,
    period_month: 4,
    period_year: 2026,
    emp_code: "B0065",
    gang_code: "B2N",
    division_code: "P1B",
    adjustment_type: "",
    adjustment_name,
    amount: 1000,
    remarks,
    category_key,
    ...extra
  };
}

const premiRecord = record("premi", "INSENTIF PANEN", "", { adjustment_type: "PREMI", ad_code: "A100", description: "INSENTIF PANEN" });
const premi = resolveCategory(premiRecord, "premi");
assert.equal(premi.adcode(premiRecord), "A100");
assert.equal(premi.description(premiRecord), "INSENTIF PANEN");

const koreksiRecord = record("koreksi", "KOREKSI UPAH", "AD CODE: D200 - (DE) KOREKSI UPAH", { adjustment_type: "POTONGAN_KOTOR" });
const koreksi = resolveCategory(koreksiRecord, "koreksi");
assert.equal(koreksi.adcode(koreksiRecord), "D200");
assert.equal(koreksi.description(koreksiRecord), "KOREKSI UPAH");

const potonganBersihRecord = record("potongan_upah_bersih", "POTONGAN PINJAMAN", "", { adjustment_type: "POTONGAN_BERSIH", ad_code: "D300" });
const potonganBersih = resolveCategory(potonganBersihRecord, "potongan_upah_bersih");
assert.equal(potonganBersih.adcode(potonganBersihRecord), "D300");
assert.equal(potonganBersih.description(potonganBersihRecord), "POTONGAN PINJAMAN");
