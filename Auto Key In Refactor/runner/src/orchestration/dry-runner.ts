import { resolveCategory } from "../categories/registry.js";
import { assignRowsToTabs } from "./row-assignment.js";
import type { RowResult, RunPayload, RunResult } from "../types.js";
import type { EmitEvent } from "./mock-runner.js";

export async function runDryRun(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const rows = payload.records.slice(0, payload.row_limit || payload.records.length);
  const rowResults: RowResult[] = [];
  const tabCount = Math.min(Math.max(1, payload.max_tabs), 10, Math.max(1, rows.length));
  const assignedRows = assignRowsToTabs(rows, tabCount, payload.category_key);

  emit({ event: "run.started", runner_mode: "dry_run", total_records: rows.length, tabs: tabCount, requested_tabs: payload.max_tabs });

  for (let tabIndex = 0; tabIndex < assignedRows.length; tabIndex++) {
    const rowsForTab = assignedRows[tabIndex];
    emit({ event: "tab.assigned", tab_index: tabIndex, assigned_rows: rowsForTab.length, first_emp_code: rowsForTab[0]?.emp_code ?? "", last_emp_code: rowsForTab[rowsForTab.length - 1]?.emp_code ?? "" });
    const tabStats = { done: 0, skipped: 0, failed: 0, total: rowsForTab.length };
    for (const record of rowsForTab) {
      emit({ event: "row.started", emp_code: record.emp_code, adjustment_name: record.adjustment_name, detail_key: record.detail_key ?? null, category_key: record.category_key ?? payload.category_key, tab_index: tabIndex });
      try {
        const category = resolveCategory(record, payload.category_key);
        const result: RowResult = {
          emp_code: record.emp_code,
          adjustment_name: record.adjustment_name,
          detail_key: record.detail_key ?? null,
          category_key: category.key,
          status: "skipped",
          message: `dry-run planned adcode ${category.adcode(record)}; no browser action`,
          tab_index: tabIndex
        };
        rowResults.push(result);
        tabStats.skipped += 1;
        emit({ event: "row.skipped", ...result });
      } catch (error) {
        const result: RowResult = {
          emp_code: record.emp_code,
          adjustment_name: record.adjustment_name,
          detail_key: record.detail_key ?? null,
          category_key: record.category_key ?? payload.category_key,
          status: "failed",
          message: error instanceof Error ? error.message : String(error),
          tab_index: tabIndex
        };
        rowResults.push(result);
        tabStats.failed += 1;
        emit({ event: "row.failed", ...result });
      }
      emit({ event: "tab.progress", tab_index: tabIndex, current_emp_code: record.emp_code, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
    }
    emit({ event: "tab.completed", tab_index: tabIndex, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
  }

  const failedRows = rowResults.filter((row) => row.status === "failed");
  const result: RunResult = {
    success: failedRows.length === 0,
    started_at,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused: false,
    total_records: rows.length,
    attempted_rows: 0,
    inserted_rows: 0,
    skipped_existing_rows: rowResults.filter((row) => row.status === "skipped").length,
    failed_rows: failedRows.length,
    error_summary: failedRows.length ? failedRows.map((row) => row.message).join("; ") : null,
    rows: rowResults
  };

  emit({ event: "run.completed", success: result.success, inserted_rows: 0, skipped_existing_rows: result.skipped_existing_rows, failed_rows: result.failed_rows });
  return result;
}
