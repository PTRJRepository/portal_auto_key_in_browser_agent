import type { Page } from "playwright";
import { PLANTWARE_CONFIG } from "../config.js";
import { resolveCategory } from "../categories/registry.js";
import { BrowserSession } from "../session/browser-session.js";
import { fillAdjustmentRow, openDetailPage, rowAlreadyExists, submitTab } from "../plantware/page-actions.js";
import type { RowResult, RunPayload, RunResult } from "../types.js";
import type { EmitEvent } from "./mock-runner.js";

export async function runMultiTabSharedSession(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const rows = payload.records.slice(0, payload.row_limit || payload.records.length);
  const requestedTabCount = payload.runner_mode.endsWith("_single") ? 1 : payload.max_tabs;
  const tabCount = Math.min(Math.max(1, requestedTabCount), PLANTWARE_CONFIG.maxTabs, Math.max(1, rows.length));
  const freshLoginFirst = payload.runner_mode === "fresh_login_single";
  const session = new BrowserSession({ headless: payload.headless, freshLoginFirst });
  const rowResults: RowResult[] = [];

  emit({ event: "run.started", runner_mode: payload.runner_mode, total_records: rows.length, tabs: tabCount, requested_tabs: payload.max_tabs });

  try {
    await session.start();
    emit({ event: "session.ready", session_reused: session.sessionReused });

    const pages: Page[] = [];
    for (let index = 0; index < tabCount; index++) {
      const page = await session.newPage();
      pages.push(page);
    }

    const assignedRows = pages.map((_, tabIndex) => rows.filter((_, index) => index % tabCount === tabIndex));
    for (let index = 0; index < assignedRows.length; index++) {
      emit({ event: "tab.assigned", tab_index: index, assigned_rows: assignedRows[index].length, first_emp_code: assignedRows[index][0]?.emp_code ?? "", last_emp_code: assignedRows[index][assignedRows[index].length - 1]?.emp_code ?? "" });
    }

    await Promise.all(pages.map(async (page, index) => {
      emit({ event: "tab.open.started", tab_index: index });
      try {
        await openDetailPage(page);
        emit({ event: "tab.form.ready", tab_index: index });
        emit({ event: "tab.ready", tab_index: index });
      } catch (error) {
        emit({ event: "tab.open.failed", tab_index: index, message: error instanceof Error ? error.message : String(error) });
        throw error;
      }
    }));

    await Promise.all(pages.map(async (page, tabIndex) => {
      const rowsForTab = assignedRows[tabIndex];
      const tabStats = { done: 0, skipped: 0, failed: 0, total: rowsForTab.length };
      for (let rowIndex = 0; rowIndex < rowsForTab.length; rowIndex++) {
        const record = rowsForTab[rowIndex];
        const category = resolveCategory(record, payload.category_key);
        emit({ event: "row.started", emp_code: record.emp_code, adjustment_name: record.adjustment_name, category_key: category.key, tab_index: tabIndex });
        try {
          if (payload.only_missing_rows && await rowAlreadyExists(page, record, category)) {
            const result: RowResult = {
              emp_code: record.emp_code,
              adjustment_name: record.adjustment_name,
              category_key: category.key,
              status: "skipped",
              message: "already exists in current Plantware page",
              tab_index: tabIndex
            };
            rowResults.push(result);
            tabStats.skipped += 1;
            emit({ event: "row.skipped", ...result });
            emit({ event: "tab.progress", tab_index: tabIndex, current_emp_code: record.emp_code, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
            continue;
          }
          await fillAdjustmentRow(page, record, category, rowIndex === 0);
          const result: RowResult = {
            emp_code: record.emp_code,
            adjustment_name: record.adjustment_name,
            category_key: category.key,
            status: "success",
            message: "row add confirmed",
            tab_index: tabIndex
          };
          rowResults.push(result);
          tabStats.done += 1;
          emit({ event: "row.success", ...result });
          emit({ event: "tab.progress", tab_index: tabIndex, current_emp_code: record.emp_code, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
        } catch (error) {
          const result: RowResult = {
            emp_code: record.emp_code,
            adjustment_name: record.adjustment_name,
            category_key: category.key,
            status: "failed",
            message: error instanceof Error ? error.message : String(error),
            tab_index: tabIndex
          };
          rowResults.push(result);
          tabStats.failed += 1;
          emit({ event: "row.failed", ...result });
          emit({ event: "tab.progress", tab_index: tabIndex, current_emp_code: record.emp_code, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
        }
      }
      emit({ event: "tab.completed", tab_index: tabIndex, done: tabStats.done, skipped: tabStats.skipped, failed: tabStats.failed, total: tabStats.total });
    }));

    for (let index = 0; index < pages.length; index++) {
      emit({ event: "tab.submit.started", tab_index: index });
      await submitTab(pages[index]);
      emit({ event: "tab.submit.completed", tab_index: index });
    }

    await Promise.all(pages.map((page) => page.close().catch(() => {})));
    const result = buildResult(payload, started_at, session.sessionReused, rows.length, rowResults, null);
    emit({ event: "run.completed", success: result.success, inserted_rows: result.inserted_rows, failed_rows: result.failed_rows });
    return result;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emit({ event: "run.failed", message });
    return buildResult(payload, started_at, session.sessionReused, rows.length, rowResults, message);
  } finally {
    await session.close();
  }
}

function buildResult(
  payload: RunPayload,
  started_at: string,
  session_reused: boolean,
  total_records: number,
  rows: RowResult[],
  error_summary: string | null
): RunResult {
  const failed_rows = rows.filter((row) => row.status === "failed").length;
  return {
    success: !error_summary && failed_rows === 0,
    started_at,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused,
    total_records,
    attempted_rows: rows.length,
    inserted_rows: rows.filter((row) => row.status === "success").length,
    skipped_existing_rows: rows.filter((row) => row.status === "skipped").length,
    failed_rows,
    error_summary,
    rows
  };
}
