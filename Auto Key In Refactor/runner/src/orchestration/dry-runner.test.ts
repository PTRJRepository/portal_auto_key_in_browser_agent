import assert from "node:assert/strict";
import { runDryRun } from "./dry-runner.js";
import type { ManualAdjustmentRecord, RunPayload } from "../types.js";

function premiumRecord(extra: Partial<ManualAdjustmentRecord>): ManualAdjustmentRecord {
  return {
    period_month: 4,
    period_year: 2026,
    emp_code: "G0352",
    emp_name: "TEST",
    gang_code: "G1H",
    division_code: "AB1",
    estate: "AB1",
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

const payload: RunPayload = {
  period_month: 4,
  period_year: 2026,
  division_code: "AB1",
  category_key: "premi",
  runner_mode: "dry_run",
  max_tabs: 2,
  headless: true,
  only_missing_rows: false,
  records: [
    premiumRecord({ detail_key: "good-row", subblok: "P0801" }),
    premiumRecord({
      adjustment_name: "PREMI JAGA",
      detail_key: "bad-row",
      ad_code: "",
      ad_code_desc: "",
      task_desc: "",
      description: "",
      subblok: "P0802"
    }),
    premiumRecord({ detail_key: "next-good-row", emp_code: "G0600", subblok: "P0803" })
  ]
};

const events: Record<string, unknown>[] = [];
const result = await runDryRun(payload, (event) => events.push(event));

assert.equal(result.success, false);
assert.equal(result.failed_rows, 1);
assert.equal(result.skipped_existing_rows, 2);
assert.match(String(result.error_summary), /PREMI detail row for G0352 \/ PREMI JAGA is missing ad_code/);
assert.deepEqual(result.rows.map((row) => row.status), ["skipped", "failed", "skipped"]);
assert.equal(events.filter((event) => event.event === "row.failed").length, 1);
assert.equal(events.filter((event) => event.event === "tab.completed").length, 2);
