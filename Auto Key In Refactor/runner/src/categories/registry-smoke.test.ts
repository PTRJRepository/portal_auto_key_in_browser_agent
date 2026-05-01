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
const pruningRecord = record("premi", "PREMI PRUNING", "", { adjustment_type: "PREMI", ad_code: "AL3PM0601", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) PRUNING)", description: "PREMI PRUNING", detail_type: "blok", subblok: "P0801" });
const rakingRecord = record("premi", "PREMI RAKING", "", { adjustment_type: "PREMI", ad_code: "AL3PM0106", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) WEEDING - CIRCLE RAKING)", description: "PREMI RAKING", detail_type: "blok", subblok: "P0901" });
const tbsRecord = record("premi", "PREMI TBS", "", { adjustment_type: "PREMI", ad_code: "(AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)", ad_code_desc: "(AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)", description: "PREMI TBS", detail_type: "blok", subblok: "P0902" });
assert.equal(premi.adcode(pruningRecord), "(AL) TUNJANGAN PREMI ((PM) PRUNING)");
assert.equal(premi.description(premiRecord), "INSENTIF PANEN");
assert.equal(premi.description(pruningRecord), "PREMI PRUNING");
assert.equal(premi.description(rakingRecord), "PREMI RAKING");
assert.equal(premi.description(tbsRecord), "PREMI TBS");

const koreksiRecord = record("koreksi", "KOREKSI UPAH", "AD CODE: D200 - (DE) KOREKSI UPAH", { adjustment_type: "POTONGAN_KOTOR" });
const koreksi = resolveCategory(koreksiRecord, "koreksi");
assert.equal(koreksi.adcode(koreksiRecord), "D200");
assert.equal(koreksi.description(koreksiRecord), "KOREKSI UPAH");

const potonganBersihRecord = record("potongan_upah_bersih", "POTONGAN PINJAMAN", "", { adjustment_type: "POTONGAN_BERSIH", ad_code: "D300" });
const potonganBersih = resolveCategory(potonganBersihRecord, "potongan_upah_bersih");
assert.equal(potonganBersih.adcode(potonganBersihRecord), "D300");
assert.equal(potonganBersih.description(potonganBersihRecord), "POTONGAN PINJAMAN");
