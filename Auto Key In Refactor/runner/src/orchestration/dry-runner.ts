import { resolveCategory } from "../categories/registry.js";
import type { RowResult, RunPayload, RunResult } from "../types.js";
import type { EmitEvent } from "./mock-runner.js";

export async function runDryRun(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const rows = payload.records.slice(0, payload.row_limit || payload.records.length);
  const rowResults: RowResult[] = [];

  emit({ event: "run.started", runner_mode: "dry_run", total_records: rows.length });

  for (let index = 0; index < rows.length; index++) {
    const record = rows[index];
    const category = resolveCategory(record, payload.category_key);
    const tab_index = index % Math.max(1, Math.min(payload.max_tabs, 10));
    const result: RowResult = {
      emp_code: record.emp_code,
      adjustment_name: record.adjustment_name,
      category_key: category.key,
      status: "skipped",
      message: `dry-run planned adcode ${category.adcode}; no browser action`,
      tab_index
    };
    rowResults.push(result);
    emit({ event: "row.skipped", ...result });
  }

  const result: RunResult = {
    success: true,
    started_at,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused: false,
    total_records: rows.length,
    attempted_rows: 0,
    inserted_rows: 0,
    skipped_existing_rows: rowResults.length,
    failed_rows: 0,
    error_summary: null,
    rows: rowResults
  };

  emit({ event: "run.completed", success: true, inserted_rows: 0, skipped_existing_rows: result.skipped_existing_rows });
  return result;
}
