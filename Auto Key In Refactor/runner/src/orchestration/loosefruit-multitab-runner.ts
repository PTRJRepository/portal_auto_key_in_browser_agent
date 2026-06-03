/**
 * Loose Fruit Brondol Multi-Tab Runner
 *
 * Multi-tab parallel processing for loose fruit brondol input.
 * Each tab gets a subset of employees, processed in parallel.
 * One browser window with multiple tabs sharing the same session.
 */

import type { Page } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";
import type { RunPayload, RunResult, LoosefruitInputRowResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { PLANTWARE_CONFIG } from "../config.js";
import {
  fetchStagingComparison,
  filterLooseFruitRows,
  deriveDivisionFromGang,
  deriveTaskCodeFromLoc,
  getLoosefruitDetailUrl,
  selectEmployee,
  selectTaskCode,
  selectChargeTo,
  selectDivisionCode,
  selectFieldNoCode,
  selectExpenseCode,
  setMT,
  setRate,
  waitForAmountNonZero,
  setTransactionDate,
  clickAdd,
  getDocumentId,
  isEmployeeAddedToGrid,
  StagingComparisonRow,
  ensurePageAlive,
} from "../plantware/loosefruit-input.js";

type Emit = (event: Record<string, unknown>) => void;

async function openLoosefruitTab(
  session: BrowserSession,
  locCode: string,
  tabIndex: number,
  emit: Emit,
  reason: string,
): Promise<Page> {
  emit({ event: "loosefruit.multitab.tab.open.started", tab_index: tabIndex, reason });
  const page = await session.newPage();
  await page.goto(getLoosefruitDetailUrl(locCode), { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
  emit({ event: "loosefruit.multitab.tab.ready", tab_index: tabIndex, url: page.url(), reason });
  return page;
}

async function ensureLoosefruitTab(
  session: BrowserSession,
  page: Page,
  locCode: string,
  tabIndex: number,
  emit: Emit,
): Promise<Page> {
  if (page.isClosed()) {
    emit({ event: "loosefruit.multitab.tab.reopen", tab_index: tabIndex, reason: "closed" });
    return await openLoosefruitTab(session, locCode, tabIndex, emit, "reopen_closed");
  }
  const alive = await ensurePageAlive(page, locCode);
  if (!alive) {
    emit({ event: "loosefruit.multitab.tab.reopen", tab_index: tabIndex, reason: "not_alive" });
    await page.close().catch(() => {});
    return await openLoosefruitTab(session, locCode, tabIndex, emit, "reopen_not_alive");
  }
  return page;
}

function isClosedPageError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /Target page, context or browser has been closed|Execution context was destroyed|Page not ready|closed/i.test(message);
}

interface TabAssignment {
  tab_index: number;
  loc_code: string;
  rows: StagingComparisonRow[];
}

interface LoosefruitCheckpoint {
  loc_code: string;
  periode: string;
  updated_at: string;
  rows: Record<string, LoosefruitInputRowResult & { updated_at?: string }>;
}

function rowCheckpointKey(row: Pick<StagingComparisonRow, "emp_code"> | Pick<LoosefruitInputRowResult, "emp_code">): string {
  return String(row.emp_code || "").trim().toUpperCase();
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

function loadCheckpoint(locCode: string, periode: string): LoosefruitCheckpoint {
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

function saveCheckpoint(checkpoint: LoosefruitCheckpoint): void {
  const filePath = checkpointPath(checkpoint.loc_code, checkpoint.periode);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  checkpoint.updated_at = new Date().toISOString();
  fs.writeFileSync(filePath, JSON.stringify(checkpoint, null, 2));
}

function rememberCheckpointRow(checkpoint: LoosefruitCheckpoint, row: LoosefruitInputRowResult): void {
  const key = rowCheckpointKey(row);
  if (!key) return;
  checkpoint.rows[key] = { ...row, updated_at: new Date().toISOString() };
  saveCheckpoint(checkpoint);
}

function completedCheckpointKeys(checkpoint: LoosefruitCheckpoint): Set<string> {
  return new Set(Object.entries(checkpoint.rows)
    .filter(([, row]) => row.status === "success" || row.status === "skipped")
    .map(([key]) => key));
}

export function uniqueRowsByEmployee(rows: StagingComparisonRow[]): StagingComparisonRow[] {
  const seen = new Set<string>();
  const uniqueRows: StagingComparisonRow[] = [];
  for (const row of rows) {
    const key = row.emp_code.trim().toUpperCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    uniqueRows.push(row);
  }
  return uniqueRows;
}

export function estateSet(rows: StagingComparisonRow[]): Set<string> {
  return new Set(rows.map(row => row.estate.trim().toUpperCase()).filter(Boolean));
}

export function assignRowsToTabs(rows: StagingComparisonRow[], tabCount: number): TabAssignment[] {
  const assignments: TabAssignment[] = [];

  // Distribute rows round-robin to ensure no overlap
  const tabRows: Map<number, StagingComparisonRow[]> = new Map();
  for (let i = 0; i < tabCount; i++) {
    tabRows.set(i, []);
  }

  for (let i = 0; i < rows.length; i++) {
    const tabIndex = i % tabCount;
    tabRows.get(tabIndex)!.push(rows[i]);
  }

  for (let i = 0; i < tabCount; i++) {
    const tabRowsList = tabRows.get(i) || [];
    if (tabRowsList.length > 0) {
      const firstRow = tabRowsList[0];
      const loc_code = firstRow.estate || "P1A";
      assignments.push({
        tab_index: i,
        loc_code,
        rows: tabRowsList,
      });
    }
  }

  return assignments;
}

export async function runLoosefruitMultiTab(
  payload: RunPayload,
  emit: Emit
): Promise<RunResult> {
  const started = new Date().toISOString();
  const staging_periode = payload.staging_periode ?? "2026-05";
  const default_loc_code = payload.loc_code ?? "P1A";
  const field_code = payload.field_code ?? " ";
  const rate = payload.rate ?? 1750;
  const doc_date = payload.doc_date ?? "31/05/2026";
  const estate_filter = payload.estate_filter ?? undefined;
  const staging_source_url = payload.staging_source_url ?? undefined;
  const headless = payload.headless ?? false;

  const rows: LoosefruitInputRowResult[] = [];

  emit({
    event: "loosefruit.multitab.run.started",
    staging_periode,
    default_loc_code,
    rate,
    doc_date,
    estate_filter
  });

  // Step 1: Fetch staging comparison data
  emit({ event: "loosefruit.multitab.fetch.start", periode: staging_periode });
  const stagingData = await fetchStagingComparison(staging_periode, staging_source_url);
  if (!stagingData || !stagingData.data) {
    emit({ event: "loosefruit.multitab.fetch.failed", message: "Failed to fetch staging data" });
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
      error_summary: "Failed to fetch staging data",
      rows: []
    };
  }

  emit({
    event: "loosefruit.multitab.fetch.success",
    total_rows: stagingData.data.rows.length,
    total_selisih: stagingData.data.totals.selisih
  });

  // Step 2: Filter loose fruit employees
  const eligibleRows = uniqueRowsByEmployee(filterLooseFruitRows(stagingData.data.rows, estate_filter));
  let filteredRows = payload.row_limit && payload.row_limit > 0 ? eligibleRows.slice(0, payload.row_limit) : eligibleRows;
  const checkpoint = loadCheckpoint(default_loc_code, staging_periode);
  const completedKeys = completedCheckpointKeys(checkpoint);
  const beforeCheckpointFilter = filteredRows.length;
  filteredRows = filteredRows.filter(row => !completedKeys.has(rowCheckpointKey(row)));
  const mixedEstates = estateSet(filteredRows);
  emit({
    event: "loosefruit.multitab.filtered",
    filtered_count: filteredRows.length,
    unique_estates: Array.from(mixedEstates),
    duplicate_rows_skipped: filterLooseFruitRows(stagingData.data.rows, estate_filter).length - eligibleRows.length,
    eligible_count: eligibleRows.length,
    row_limit: payload.row_limit ?? null,
    checkpoint_skipped: beforeCheckpointFilter - filteredRows.length,
    checkpoint_path: checkpointPath(default_loc_code, staging_periode),
  });

  if (mixedEstates.size > 1) {
    const message = `Mixed estate rows in one loosefruit session: ${Array.from(mixedEstates).join(", ")}`;
    emit({ event: "loosefruit.multitab.mixed_estate", message });
    return {
      success: false,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: false,
      total_records: filteredRows.length,
      attempted_rows: 0,
      inserted_rows: 0,
      skipped_existing_rows: 0,
      failed_rows: 0,
      error_summary: message,
      rows: []
    };
  }

  if (filteredRows.length === 0) {
    emit({ event: "loosefruit.multitab.no_rows", message: "No rows with positive selisih to input" });
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
      rows: []
    };
  }

  // Step 3: Determine tab count
  const requestedTabCount = 1;
  const tabCount = Math.min(Math.max(1, requestedTabCount), PLANTWARE_CONFIG.maxTabs, Math.max(1, filteredRows.length));
  const loc_code = Array.from(mixedEstates)[0] || default_loc_code;

  emit({ event: "loosefruit.multitab.tab_count", requested: requestedTabCount, actual: tabCount });

  // Step 4: Assign rows to tabs
  const assignments = assignRowsToTabs(filteredRows, tabCount);
  for (const assignment of assignments) {
    emit({
      event: "loosefruit.multitab.tab.assigned",
      tab_index: assignment.tab_index,
      loc_code: assignment.loc_code,
      assigned_rows: assignment.rows.length,
      first_emp_code: assignment.rows[0]?.emp_code ?? "",
    });
  }

  // Step 5: Start browser session
  const session = new BrowserSession({
    headless,
    freshLoginFirst: true,
    loginFallback: false,
    division: loc_code
  });

  let sessionReused = false;

  try {
    await session.start();
    sessionReused = session.sessionReused;
    emit({
      event: "session.ready",
      division_code: loc_code,
      reused: sessionReused,
      session_path: session.getSessionPath()
    });

    // Step 6: Create pages (tabs)
    const pages: Page[] = [];
    for (let index = 0; index < tabCount; index++) {
      const page = await session.newPage();
      pages.push(page);
    }

    // Step 7: Navigate each tab to the loosefruit page. Keep other tabs alive if one tab fails.
    const tabReady = new Set<number>();
    const openResults = await Promise.allSettled(pages.map(async (page, index) => {
      if (index > 0) await new Promise((resolve) => setTimeout(resolve, index * 1500));
      emit({ event: "loosefruit.multitab.tab.open.started", tab_index: index });
      await page.goto(getLoosefruitDetailUrl(loc_code), { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
      tabReady.add(index);
      emit({ event: "loosefruit.multitab.tab.ready", tab_index: index, url: page.url() });
    }));
    openResults.forEach((result, index) => {
      if (result.status === "rejected") {
        emit({ event: "loosefruit.multitab.tab.open.failed", tab_index: index, message: result.reason instanceof Error ? result.reason.message : String(result.reason) });
      }
    });

    // Step 8: Process rows in parallel across tabs. Each tab owns one page in the same browser window/session.
    emit({ event: "loosefruit.multitab.check_existing.start", message: "Checking existing employees in Plantware..." });
    const existingEmpCodes = new Set<string>();
    for (const page of pages) {
      try {
        const existing = await page.evaluate(() => {
          const grid = document.querySelector("#MainContent_grvDetail");
          if (!grid) return [];
          const cells = grid.querySelectorAll("td");
          const empCodes: string[] = [];
          for (const cell of cells) {
            const text = cell.textContent?.trim() || "";
            if (/^[A-Z]\d{4}$/.test(text)) empCodes.push(text);
          }
          return empCodes;
        });
        existing.forEach(code => existingEmpCodes.add(code));
      } catch (e) {
        // Ignore errors checking existing
      }
    }
    emit({ event: "loosefruit.multitab.check_existing.done", existing_count: existingEmpCodes.size });

        // Process tabs sequentially to preserve per-tab page state.
    // DO NOT use Promise.allSettled for tab processing — adding tabs during parallel
    // execution resets page document state and wipes already-added grid rows.
    for (let tabIdx = 0; tabIdx < tabCount; tabIdx++) {
      const assignment = assignments.find(a => a.tab_index === tabIdx);
      if (!assignment) continue;

      const tabPage = pages[tabIdx];

      if (!tabReady.has(tabIdx)) {
        const failedRows = assignment.rows.map(row => ({
          emp_code: row.emp_code,
          emp_name: row.emp_name,
          gang: row.gang,
          selisih: row.selisih,
          status: "failed" as const,
          message: "Tab failed to open",
          tab_index: tabIdx,
        }));
        rows.push(...failedRows);
        failedRows.forEach(row => rememberCheckpointRow(checkpoint, row));
        emit({ event: "loosefruit.multitab.tab.completed", tab_index: tabIdx, done: 0, skipped: 0, failed: assignment.rows.length, total: assignment.rows.length });
        continue;
      }

      let page = tabPage;
      emit({ event: "loosefruit.multitab.tab.processing", tab_index: tabIdx, rows: assignment.rows.length });

      const tabRows: LoosefruitInputRowResult[] = [];
      const tabStats = { done: 0, skipped: 0, failed: 0, total: assignment.rows.length };

      for (let rowIndex = 0; rowIndex < assignment.rows.length; rowIndex++) {
        const row = assignment.rows[rowIndex];
        page = await ensureLoosefruitTab(session, page, loc_code, tabIdx, emit);

        const normalizedEmpCode = row.emp_code.trim().toUpperCase();

        if (existingEmpCodes.has(normalizedEmpCode)) {
          const existingDocId = await getDocumentId(page).catch(() => null);
          tabRows.push({
            emp_code: row.emp_code,
            emp_name: row.emp_name,
            gang: row.gang,
            selisih: row.selisih,
            status: "skipped",
            message: "Employee already exists in Plantware grid",
            doc_id: existingDocId,
            mt: row.selisih,
            amount: row.selisih * rate,
            tab_index: tabIdx,
          });
          tabStats.skipped += 1;
          emit({ event: "loosefruit.multitab.row.skipped", tab_index: tabIdx, emp_code: row.emp_code, reason: "already_in_plantware" });
          await page.waitForTimeout(200).catch(() => {});
          continue;
        }

        existingEmpCodes.add(normalizedEmpCode);
        const taskCode = deriveTaskCodeFromLoc(loc_code);
        const divisionCode = deriveDivisionFromGang(row.gang);

        emit({
          event: "loosefruit.multitab.row.started",
          tab_index: tabIdx,
          index: rowIndex + 1,
          total: assignment.rows.length,
          emp_code: row.emp_code,
          gang: row.gang,
          selisih: row.selisih
        });

        let success = false;
        for (let attempt = 0; attempt < 2 && !success; attempt++) {
          try {
            const alive = await ensurePageAlive(page, loc_code);
            if (!alive) {
              emit({ event: "loosefruit.multitab.row.reloading_dead_tab", tab_index: tabIdx, emp_code: row.emp_code });
            }

            const url = getLoosefruitDetailUrl(loc_code);
            await page.goto(url, { waitUntil: "load", timeout: 30000 }).catch((e) => {
              emit({ event: "loosefruit.multitab.tab.goto.failed", tab_index: tabIdx, url, error: String(e) });
            });

            await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 }).catch(() => {});

            const stillAlive = await ensurePageAlive(page, loc_code);
            if (!stillAlive) {
              if (attempt === 0) {
                emit({ event: "loosefruit.multitab.row.page_dead_after_load", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 });
                continue;
              } else {
                tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page context dead after reload", tab_index: tabIdx });
                tabStats.failed += 1;
                break;
              }
            }

            await selectChargeTo(page, loc_code);
            await page.waitForTimeout(500);

            const afterChargeAlive = await ensurePageAlive(page, loc_code);
            if (!afterChargeAlive) {
              if (attempt === 0) {
                emit({ event: "loosefruit.multitab.row.page_dead_after_charge", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 });
                continue;
              } else {
                tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead after ChargeTo postback", tab_index: tabIdx });
                tabStats.failed += 1;
                break;
              }
            }

            await setTransactionDate(page, doc_date);
            await page.waitForTimeout(300);

            const beforeEmpAlive = await ensurePageAlive(page, loc_code);
            if (!beforeEmpAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_emp", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before emp select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            await selectEmployee(page, row.emp_code);
            await page.waitForTimeout(500);

            const beforeTaskAlive = await ensurePageAlive(page, loc_code);
            if (!beforeTaskAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_task", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before task select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            await selectTaskCode(page, taskCode);
            await page.waitForTimeout(500);

            const beforeDivAlive = await ensurePageAlive(page, loc_code);
            if (!beforeDivAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_div", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before div select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            await selectDivisionCode(page, divisionCode);
            await page.waitForTimeout(500);

            const beforeFieldAlive = await ensurePageAlive(page, loc_code);
            if (!beforeFieldAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_field", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before field select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            await selectFieldNoCode(page, field_code);
            await page.waitForTimeout(300);

            await selectExpenseCode(page);
            await page.waitForTimeout(300);

            await setMT(page, row.selisih);
            await setRate(page, rate);
            const calculatedAmount = await waitForAmountNonZero(page);
            emit({ event: "loosefruit.multitab.amount.ready", tab_index: tabIdx, emp_code: row.emp_code, amount: calculatedAmount });
            await page.waitForTimeout(200).catch(() => {});

            const formState = await page.evaluate(() => {
              return {
                chargeTo: (document.querySelector("#MainContent_ddlChargeTo") as HTMLSelectElement)?.value,
                employee: (document.querySelector("#MainContent_ddlEmployee") as HTMLSelectElement)?.value,
                taskCode: (document.querySelector("#MainContent_ddlTaskCode") as HTMLSelectElement)?.value,
                division: (document.querySelector("#MainContent_MultiDimAcc_ddlBlock") as HTMLSelectElement)?.value,
                field: (document.querySelector("#MainContent_MultiDimAcc_ddlSubBlk") as HTMLSelectElement)?.value,
                expense: (document.querySelector("#MainContent_MultiDimAcc_ddlExpCode") as HTMLSelectElement)?.value,
                trxDate: (document.querySelector("#MainContent_txtTrxDate") as HTMLInputElement)?.value,
                mt: (document.querySelector("#MainContent_txtMT") as HTMLInputElement)?.value,
                rate: (document.querySelector("#MainContent_txtRate") as HTMLInputElement)?.value,
                addVisible: !!document.querySelector("#MainContent_btnAdd"),
                docIdDisabled: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.disabled,
                docId: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.value,
              };
            }).catch(e => ({ error: String(e) }));
            emit({ event: "loosefruit.multitab.row.pre_add_state", tab_index: tabIdx, emp_code: row.emp_code, ...formState });
            await clickAdd(page, `debug/pre-add-${row.emp_code}.png`);
            const afterState = await page.evaluate(() => {
              return {
                pageUrl: window.location.href,
                docIdDisabled: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.disabled,
                docId: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.value,
              };
            }).catch(e => ({ error: String(e) }));
            emit({ event: "loosefruit.multitab.row.post_add_state", tab_index: tabIdx, emp_code: row.emp_code, ...afterState });

            const gridCheck = await isEmployeeAddedToGrid(page, row.emp_code);
            if (gridCheck.added) {
              tabRows.push({
                emp_code: row.emp_code,
                emp_name: row.emp_name,
                gang: row.gang,
                selisih: row.selisih,
                status: "success",
                message: "Row added successfully",
                doc_id: gridCheck.docId,
                mt: row.selisih,
                amount: row.selisih * rate,
                tab_index: tabIdx,
              });
              tabStats.done += 1;
              existingEmpCodes.add(row.emp_code);
              emit({ event: "loosefruit.multitab.row.success", tab_index: tabIdx, emp_code: row.emp_code, doc_id: gridCheck.docId });
              success = true;
            } else {
              if (attempt === 0) {
                tabRows.push({
                  emp_code: row.emp_code,
                  emp_name: row.emp_name,
                  gang: row.gang,
                  selisih: row.selisih,
                  status: "failed",
                  message: "Document ID not generated after Add",
                  tab_index: tabIdx,
                });
                tabStats.failed += 1;
                emit({ event: "loosefruit.multitab.row.failed", tab_index: tabIdx, emp_code: row.emp_code, reason: "no_doc_id" });
              }
            }
          } catch (error) {
            if (attempt === 0) {
              emit({ event: "loosefruit.multitab.row.retry", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1, error: String(error) });
              if (isClosedPageError(error)) {
                page = await openLoosefruitTab(session, loc_code, tabIdx, emit, "retry_after_closed_page");
              }
            } else {
              tabRows.push({
                emp_code: row.emp_code,
                emp_name: row.emp_name,
                gang: row.gang,
                selisih: row.selisih,
                status: "failed",
                message: error instanceof Error ? error.message : String(error),
                tab_index: tabIdx,
              });
              tabStats.failed += 1;
              emit({ event: "loosefruit.multitab.row.error", tab_index: tabIdx, emp_code: row.emp_code, error: String(error) });
            }
          }
        }

        emit({ event: "loosefruit.multitab.tab.progress", tab_index: tabIdx, ...tabStats });
        await page.waitForTimeout(200).catch(() => {});
      }

      emit({ event: "loosefruit.multitab.tab.completed", tab_index: tabIdx, ...tabStats });
      tabRows.forEach(row => rememberCheckpointRow(checkpoint, row));
      rows.push(...tabRows);
    }


    emit({ event: "loosefruit.multitab.run.completed", total_processed: rows.length });

  } finally {
    const shouldKeepOpen = Boolean(payload.keep_browser_open_on_error) && rows.some(row => row.status === "failed");
    if (shouldKeepOpen) {
      emit({ event: "loosefruit.multitab.browser.kept_open", reason: "failed_rows", failed_rows: rows.filter(row => row.status === "failed").length });
    } else {
      await session.close();
    }
  }

  const successRows = rows.filter(r => r.status === "success").length;
  const skippedRows = rows.filter(r => r.status === "skipped").length;
  const failedRows = rows.filter(r => r.status === "failed").length;

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
    rows
  };
}
