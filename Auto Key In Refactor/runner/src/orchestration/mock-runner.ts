import type { RowResult, RunPayload, RunResult } from "../types.js";
import { resolveCategory } from "../categories/registry.js";

export type EmitEvent = (event: Record<string, unknown>) => void;

export async function runMock(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const rows = payload.records.slice(0, payload.row_limit || payload.records.length);
  const rowResults: RowResult[] = [];

  emit({ event: "run.started", runner_mode: payload.runner_mode, total_records: rows.length });

  for (let index = 0; index < rows.length; index++) {
    const record = rows[index];
    const category = resolveCategory(record, payload.category_key);
    const tab_index = index % Math.max(1, Math.min(payload.max_tabs, 10));
    await new Promise((resolve) => setTimeout(resolve, 10));
    const result: RowResult = {
      emp_code: record.emp_code,
      adjustment_name: record.adjustment_name,
      detail_key: record.detail_key ?? null,
      category_key: category.key,
      status: "success",
      message: `mock input using adcode ${category.adcode(record)}`,
      tab_index
    };
    rowResults.push(result);
    emit({ event: "row.success", ...result });
  }

  const finished_at = new Date().toISOString();
  const result: RunResult = {
    success: true,
    started_at,
    finished_at,
    runner_mode: payload.runner_mode,
    session_reused: false,
    total_records: rows.length,
    attempted_rows: rows.length,
    inserted_rows: rowResults.filter((row) => row.status === "success").length,
    skipped_existing_rows: rowResults.filter((row) => row.status === "skipped").length,
    failed_rows: rowResults.filter((row) => row.status === "failed").length,
    error_summary: null,
    rows: rowResults
  };

  emit({ event: "run.completed", success: true, inserted_rows: result.inserted_rows });
  return result;
}
