/**
 * Loose Fruit CSV Single-Division Runner
 *
 * Reads loosefruit staging-comparison data from a local CSV file and processes
 * one division at a time. Designed for single-division-per-execution workflow.
 *
 * Data source: local CSV file (columns: EmpCode, Nama, Gang, Div, 1S-31S, 1P-31P, TotalS, TotalP)
 * Target page: http://plantwarep3:8001/en/PR/trx/frmPrTrxLooseFruitDet.aspx
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { RunPayload, RunResult, LoosefruitInputRowResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import {
  loadStagingComparisonFromCsv,
  filterLooseFruitRows,
  deriveDivisionFromGang,
  deriveTaskCodeFromLoc,
  getLoosefruitDetailUrl,
  selectChargeTo,
  setTransactionDate,
  selectEmployee,
  selectTaskCode,
  selectDivisionCode,
  selectFieldNoCode,
  selectExpenseCode,
  setMT,
  setRate,
  clickAdd,
  getDocumentId,
  isEmployeeAddedToGrid,
  ensurePageAlive,
  StagingComparisonRow,
} from "../plantware/loosefruit-input.js";

type Emit = (event: Record<string, unknown>) => void;

// ---------------------------------------------------------------------------
// Checkpoint types and utilities
// ---------------------------------------------------------------------------

interface LoosefruitCsvCheckpoint {
  loc_code: string;
  periode: string;
  updated_at: string;
  rows: Record<string, LoosefruitInputRowResult & { updated_at?: string }>;
}

function rowCheckpointKey(empCode: string): string {
  return String(empCode || "").trim().toUpperCase();
}

function checkpointBaseDir(): string {
  const cwd = process.cwd();
  return path.basename(cwd).toLowerCase() === "runner"
    ? path.resolve(cwd, "data/loosefruit-checkpoints")
    : path.resolve(cwd, "runner/data/loosefruit-checkpoints");
}

function safeFilePart(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9_-]+/g, "_") || "UNKNOWN";
}

function checkpointPath(locCode: string, periode: string): string {
  return path.join(checkpointBaseDir(), `loosefruit-${safeFilePart(locCode)}-${safeFilePart(periode)}.json`);
}

function loadCheckpoint(locCode: string, periode: string): LoosefruitCsvCheckpoint {
  const filePath = checkpointPath(locCode, periode);
  if (!fs.existsSync(filePath)) {
    return { loc_code: locCode, periode, updated_at: new Date().toISOString(), rows: {} };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    return {
      loc_code: String(parsed.loc_code || locCode),
      periode: String(parsed.periode || periode),
      updated_at: String(parsed.updated_at || new Date().toISOString()),
      rows: typeof parsed.rows === "object" && parsed.rows ? parsed.rows : {},
    };
  } catch {
    return { loc_code: locCode, periode, updated_at: new Date().toISOString(), rows: {} };
  }
}

function saveCheckpoint(checkpoint: LoosefruitCsvCheckpoint): void {
  const filePath = checkpointPath(checkpoint.loc_code, checkpoint.periode);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  checkpoint.updated_at = new Date().toISOString();
  fs.writeFileSync(filePath, JSON.stringify(checkpoint, null, 2));
}

function rememberCheckpointRow(checkpoint: LoosefruitCsvCheckpoint, row: LoosefruitInputRowResult): void {
  const key = rowCheckpointKey(row.emp_code);
  if (!key) return;
  checkpoint.rows[key] = { ...row, updated_at: new Date().toISOString() };
  saveCheckpoint(checkpoint);
}

function completedCheckpointKeys(checkpoint: LoosefruitCsvCheckpoint): Set<string> {
  return new Set(Object.entries(checkpoint.rows)
    .filter(([, r]) => r.status === "success" || r.status === "skipped")
    .map(([key]) => key));
}

// ---------------------------------------------------------------------------
// Main runner
// ---------------------------------------------------------------------------

export async function runLoosefruitCsvSingle(
  payload: RunPayload,
  emit: Emit
): Promise<RunResult> {
  const started = new Date().toISOString();

  // Parse payload fields
  const csv_path = payload.csv_path ?? (() => { throw new Error("csv_path is required for input_loosefruit_csv_single operation"); })();
  const staging_periode = payload.staging_periode ?? "2026-05";
  const loc_code = payload.loc_code ?? "P1A";
  const field_code = payload.field_code ?? " ";
  const rate = payload.rate ?? 1750;
  const doc_date = payload.doc_date ?? "31/05/2026";
  const headless = payload.headless ?? false;
  const row_limit = payload.row_limit ?? null;
  const division_filter = payload.division_filter ?? null;

  emit({
    event: "loosefruit.csv_single.run.started",
    csv_path,
    staging_periode,
    loc_code,
    rate,
    doc_date,
    division_filter,
    row_limit,
  });

  // Step 1: Load CSV via loadStagingComparisonFromCsv
  emit({ event: "loosefruit.csv_single.csv.load.start", csv_path, periode: staging_periode });
  let stagingData: ReturnType<typeof loadStagingComparisonFromCsv>;
  try {
    stagingData = loadStagingComparisonFromCsv(csv_path, staging_periode);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    emit({ event: "loosefruit.csv_single.csv.load.failed", message });
    return {
      success: false,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: false,
      total_records: 0,
      attempted_rows: 0,
      inserted_rows: 0,
      skipped_existing_rows: 0,
      failed_rows: 0,
      error_summary: `CSV load failed: ${message}`,
      rows: [],
    };
  }

  if (!stagingData.success || !stagingData.data) {
    emit({ event: "loosefruit.csv_single.csv.load.failed", message: "CSV returned no data" });
    return {
      success: false,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: false,
      total_records: 0,
      attempted_rows: 0,
      inserted_rows: 0,
      skipped_existing_rows: 0,
      failed_rows: 0,
      error_summary: "CSV returned no data",
      rows: [],
    };
  }

  emit({
    event: "loosefruit.csv_single.csv.load.success",
    total_rows: stagingData.data.rows.length,
    total_selisih: stagingData.data.totals.selisih,
  });

  // Step 2: Group rows by estate (div column) via row.estate
  const grouped = new Map<string, StagingComparisonRow[]>();
  for (const row of stagingData.data.rows) {
    const divKey = row.estate.trim().toUpperCase();
    if (!divKey) continue;
    if (!grouped.has(divKey)) grouped.set(divKey, []);
    grouped.get(divKey)!.push(row);
  }

  emit({
    event: "loosefruit.csv_single.divisions.discovered",
    divisions: Array.from(grouped.keys()),
    total_divisions: grouped.size,
  });

  // Step 3: Select single division to process
  let targetDivision: string;
  if (division_filter) {
    const upperFilter = division_filter.trim().toUpperCase();
    if (!grouped.has(upperFilter)) {
      emit({ event: "loosefruit.csv_single.division.not_found", division_filter: upperFilter, available: Array.from(grouped.keys()) });
      return {
        success: false,
        started_at: started,
        finished_at: new Date().toISOString(),
        runner_mode: payload.runner_mode,
        session_reused: false,
        total_records: 0,
        attempted_rows: 0,
        inserted_rows: 0,
        skipped_existing_rows: 0,
        failed_rows: 0,
        error_summary: `Division "${upperFilter}" not found in CSV`,
        rows: [],
      };
    }
    targetDivision = upperFilter;
  } else {
    targetDivision = grouped.keys().next().value!;
  }

  const divisionRows = grouped.get(targetDivision)!;

  // Step 4: Filter eligible rows (positive selisih) and apply checkpoint
  const eligibleRows = filterLooseFruitRows(divisionRows);
  const rawLimit = row_limit !== null && row_limit > 0 ? row_limit : null;
  let filteredRows = rawLimit ? eligibleRows.slice(0, rawLimit) : eligibleRows;

  const checkpoint = loadCheckpoint(targetDivision, staging_periode);
  const completedKeys = completedCheckpointKeys(checkpoint);
  const beforeCheckpointCount = filteredRows.length;
  filteredRows = filteredRows.filter(row => !completedKeys.has(rowCheckpointKey(row.emp_code)));

  emit({
    event: "loosefruit.csv_single.division.started",
    division: targetDivision,
    eligible_rows: eligibleRows.length,
    checkpoint_skipped: beforeCheckpointCount - filteredRows.length,
    checkpoint_path: checkpointPath(targetDivision, staging_periode),
    rows_to_process: filteredRows.length,
  });

  if (filteredRows.length === 0) {
    emit({ event: "loosefruit.csv_single.no_rows", message: "No rows with positive selisih to input" });
    return {
      success: true,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: false,
      total_records: 0,
      attempted_rows: 0,
      inserted_rows: 0,
      skipped_existing_rows: 0,
      failed_rows: 0,
      error_summary: null,
      rows: [],
    };
  }

  // Step 5: Start browser session
  const session = new BrowserSession({
    headless,
    freshLoginFirst: true,
    loginFallback: false,
    division: targetDivision,
  });

  let sessionReused = false;
  const rows: LoosefruitInputRowResult[] = [];

  try {
    await session.start();
    sessionReused = session.sessionReused;
    emit({
      event: "session.ready",
      division_code: targetDivision,
      reused: sessionReused,
      session_path: session.getSessionPath(),
    });

    // Step 6: Open loosefruit detail page
    let page = await session.newPage();
    await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
    await page.waitForTimeout(2000);
    emit({ event: "loosefruit.csv_single.page.loaded", url: page.url() });

    // Step 7: Process each row
    for (let i = 0; i < filteredRows.length; i++) {
      const row = filteredRows[i];
      const empKey = rowCheckpointKey(row.emp_code);

      emit({
        event: "loosefruit.csv_single.row.started",
        index: i + 1,
        total: filteredRows.length,
        emp_code: row.emp_code,
        gang: row.gang,
        estate: row.estate,
        selisih: row.selisih,
      });

      // Retry loop: up to 2 attempts per row
      let success = false;
      for (let attempt = 0; attempt < 2 && !success; attempt++) {
        try {
          // For attempt >= 1, reload page. For attempt 0, check if URL is still valid (not a postback URL)
          if (attempt > 0) {
            emit({ event: "loosefruit.csv_single.row.reloading", emp_code: row.emp_code, attempt });
            try { await page.close(); } catch {}
            page = await session.newPage();
            await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 30000 });
            await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
            await page.waitForTimeout(2000);
            emit({ event: "loosefruit.csv_single.row.reloaded", emp_code: row.emp_code });
          } else {
            // On first attempt, check if page URL is valid (not a postback URL)
            const url = page.url();
            const needsReload = !url || url === "about:blank" || url.includes("__doPostBack") || url.includes("javascript");
            if (needsReload) {
              emit({ event: "loosefruit.csv_single.row.url_invalid", emp_code: row.emp_code, url });
              try { await page.close(); } catch {}
              page = await session.newPage();
              await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 30000 });
              await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
              await page.waitForTimeout(2000);
            }
          }

          // Step A: Set Charge To (reveals employee dropdown)
          await selectChargeTo(page, targetDivision);
          await page.waitForTimeout(500);

          // Verify page alive after postback
          if (!(await ensurePageAlive(page, targetDivision))) {
            if (attempt === 0) {
              emit({ event: "loosefruit.csv_single.row.page_dead_after_charge", emp_code: row.emp_code, attempt });
              continue; // retry
            }
            throw new Error("Page context dead after ChargeTo postback");
          }

          // Step B: Set Transaction Date
          await setTransactionDate(page, doc_date);
          await page.waitForTimeout(300);

          // Step C: Check if employee already exists in grid (before adding)
          const gridCheck = await isEmployeeAddedToGrid(page, row.emp_code);
          if (gridCheck.added) {
            const existingDocId = gridCheck.docId ?? await getDocumentId(page).catch(() => null);
            const result: LoosefruitInputRowResult = {
              emp_code: row.emp_code,
              emp_name: row.emp_name,
              gang: row.gang,
              selisih: row.selisih,
              status: "skipped",
              message: "Employee already in Plantware grid",
              doc_id: existingDocId,
              mt: row.selisih,
              amount: row.selisih * rate,
            };
            rows.push(result);
            rememberCheckpointRow(checkpoint, result);
            emit({ event: "loosefruit.csv_single.row.skipped", emp_code: row.emp_code });
            await page.waitForTimeout(300);
            success = true;
            break;
          }

          // Step D: Select employee
          if (!(await ensurePageAlive(page, targetDivision))) {
            if (attempt === 0) { emit({ event: "loosefruit.csv_single.row.page_dead_before_emp", emp_code: row.emp_code, attempt }); continue; }
            throw new Error("Page dead before employee select");
          }
          await selectEmployee(page, row.emp_code);
          await page.waitForTimeout(500);

          // Step E: Select task code
          if (!(await ensurePageAlive(page, targetDivision))) {
            if (attempt === 0) { emit({ event: "loosefruit.csv_single.row.page_dead_before_task", emp_code: row.emp_code, attempt }); continue; }
            throw new Error("Page dead before task select");
          }
          const taskCode = deriveTaskCodeFromLoc(targetDivision);
          await selectTaskCode(page, taskCode);
          await page.waitForTimeout(500);

          // Step F: Select division code
          if (!(await ensurePageAlive(page, targetDivision))) {
            if (attempt === 0) { emit({ event: "loosefruit.csv_single.row.page_dead_before_div", emp_code: row.emp_code, attempt }); continue; }
            throw new Error("Page dead before division select");
          }
          const divisionCode = deriveDivisionFromGang(row.gang);
          await selectDivisionCode(page, divisionCode);
          await page.waitForTimeout(500);

          // Step G: Select field no code
          if (!(await ensurePageAlive(page, targetDivision))) {
            if (attempt === 0) { emit({ event: "loosefruit.csv_single.row.page_dead_before_field", emp_code: row.emp_code, attempt }); continue; }
            throw new Error("Page dead before field select");
          }
          await selectFieldNoCode(page, field_code);
          await page.waitForTimeout(300);

          // Step H: Select expense code (Labour)
          await selectExpenseCode(page);
          await page.waitForTimeout(300);

          // Step I: Set MT and Rate, wait for amount
          await setMT(page, row.selisih);
          await setRate(page, rate);
          // Wait for ASP.NET to compute the amount — poll with a long timeout
          let calculatedAmount = 0;
          let amountResolved = false;
          for (let poll = 0; poll < 30 && !amountResolved; poll++) {
            try {
              await page.waitForTimeout(1000);
              calculatedAmount = await page.evaluate(() => {
                for (const sel of [
                  "#MainContent_lblTotalAmount", "span[id$='lblTotalAmount']",
                  "#MainContent_txtAmount", "input[id$='txtAmount']", "#MainContent_txtAmt"
                ]) {
                  const el = document.querySelector(sel) as HTMLInputElement | HTMLElement | null;
                  if (!el) continue;
                  const val = el instanceof HTMLInputElement ? el.value : (el.textContent || "");
                  const num = Number(String(val).replace(/,/g, ""));
                  if (Number.isFinite(num) && num > 0) return num;
                }
                return 0;
              });
              if (calculatedAmount > 0) amountResolved = true;
            } catch {
              break;
            }
          }
          if (!amountResolved) {
            if (attempt === 0) {
              emit({ event: "loosefruit.csv_single.row.amount_timeout_retry", emp_code: row.emp_code, attempt });
              continue; // retry: reload page and try again
            }
            const result: LoosefruitInputRowResult = {
              emp_code: row.emp_code,
              emp_name: row.emp_name,
              gang: row.gang,
              selisih: row.selisih,
              status: "failed",
              message: "Amount remains zero after Rate postback (30s timeout)",
            };
            rows.push(result);
            rememberCheckpointRow(checkpoint, result);
            emit({ event: "loosefruit.csv_single.row.failed", emp_code: row.emp_code, message: result.message });
            break;
          }
          emit({ event: "loosefruit.csv_single.amount.ready", emp_code: row.emp_code, amount: calculatedAmount });
          await page.waitForTimeout(300);

          // Step J: Click Add — wait for page to settle after postback before checking grid
          await clickAdd(page);
          // Wait for ASP.NET postback to complete — use domcontentloaded since load times out
          await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => {});
          await page.waitForTimeout(2000); // allow DOM to fully update

          // Step K: Verify employee was added to grid
          if (!(await ensurePageAlive(page, targetDivision))) {
            // Page died after add — reload and check
            await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 20000 }).catch(() => {});
            await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 10000 }).catch(() => {});
            await page.waitForTimeout(1500);
          }
          const afterAddCheck = await isEmployeeAddedToGrid(page, row.emp_code);
          if (afterAddCheck.added) {
            const result: LoosefruitInputRowResult = {
              emp_code: row.emp_code,
              emp_name: row.emp_name,
              gang: row.gang,
              selisih: row.selisih,
              status: "success",
              message: "Row added successfully",
              doc_id: afterAddCheck.docId,
              mt: row.selisih,
              amount: row.selisih * rate,
            };
            rows.push(result);
            rememberCheckpointRow(checkpoint, result);
            emit({ event: "loosefruit.csv_single.row.success", emp_code: row.emp_code, doc_id: afterAddCheck.docId });
            success = true;
          } else {
            // Add did not succeed - may need retry or mark failed
            if (attempt === 0) {
              emit({ event: "loosefruit.csv_single.row.add_failed_retry", emp_code: row.emp_code, attempt });
              continue; // retry
            }
            const result: LoosefruitInputRowResult = {
              emp_code: row.emp_code,
              emp_name: row.emp_name,
              gang: row.gang,
              selisih: row.selisih,
              status: "failed",
              message: "Employee not found in grid after Add",
            };
            rows.push(result);
            rememberCheckpointRow(checkpoint, result);
            emit({ event: "loosefruit.csv_single.row.failed", emp_code: row.emp_code, message: result.message });
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          if (attempt === 0) {
            emit({ event: "loosefruit.csv_single.row.retry", emp_code: row.emp_code, attempt: attempt + 1, error: message });
          } else {
            const result: LoosefruitInputRowResult = {
              emp_code: row.emp_code,
              emp_name: row.emp_name,
              gang: row.gang,
              selisih: row.selisih,
              status: "failed",
              message,
            };
            rows.push(result);
            rememberCheckpointRow(checkpoint, result);
            emit({ event: "loosefruit.csv_single.row.failed", emp_code: row.emp_code, message });
          }
        }
      }

      await page.waitForTimeout(300);

      // If page is dead after row processing, reopen it before next row
      try {
        if (!(await ensurePageAlive(page, targetDivision))) {
          emit({ event: "loosefruit.csv_single.page.reopening", reason: "page_dead_after_row", index: i + 1 });
          await page.close();
          page = await session.newPage();
          await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 30000 });
          await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
          await page.waitForTimeout(1500);
        }
      } catch {
        // Page context is dead — create a new page
        emit({ event: "loosefruit.csv_single.page.recreating", reason: "context_closed_after_row", index: i + 1 });
        try { await page.close(); } catch {}
        page = await session.newPage();
        await page.goto(getLoosefruitDetailUrl(targetDivision), { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
        await page.waitForTimeout(1500);
      }
    }

    emit({ event: "loosefruit.csv_single.division.completed", division: targetDivision, processed: rows.length });

  } finally {
    await session.close();
  }

  const successRows = rows.filter(r => r.status === "success").length;
  const skippedRows = rows.filter(r => r.status === "skipped").length;
  const failedRows = rows.filter(r => r.status === "failed").length;

  emit({ event: "loosefruit.csv_single.run.completed", processed: rows.length, success: successRows, skipped: skippedRows, failed: failedRows });

  return {
    success: failedRows === 0,
    started_at: started,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused: sessionReused,
    total_records: filteredRows.length,
    attempted_rows: rows.length,
    inserted_rows: successRows,
    skipped_existing_rows: skippedRows,
    failed_rows: failedRows,
    error_summary: failedRows > 0 ? `${failedRows} rows failed` : null,
    rows,
  };
}