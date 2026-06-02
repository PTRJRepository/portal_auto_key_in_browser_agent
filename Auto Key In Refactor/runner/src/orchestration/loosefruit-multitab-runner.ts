/**
 * Loose Fruit Brondol Multi-Tab Runner
 *
 * Multi-tab parallel processing for loose fruit brondol input.
 * Each tab gets a subset of employees, processed in parallel.
 * One browser window with multiple tabs sharing the same session.
 */

import type { Page } from "playwright";
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
  setTransactionDate,
  clickAdd,
  getDocumentId,
  StagingComparisonRow,
  ensurePageAlive,
} from "../plantware/loosefruit-input.js";

type Emit = (event: Record<string, unknown>) => void;

interface TabAssignment {
  tab_index: number;
  loc_code: string;
  rows: StagingComparisonRow[];
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
  const stagingData = await fetchStagingComparison(staging_periode, staging_source_url, default_loc_code);
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
  const filteredRows = payload.row_limit && payload.row_limit > 0 ? eligibleRows.slice(0, payload.row_limit) : eligibleRows;
  const mixedEstates = estateSet(filteredRows);
  emit({
    event: "loosefruit.multitab.filtered",
    filtered_count: filteredRows.length,
    unique_estates: Array.from(mixedEstates),
    duplicate_rows_skipped: filterLooseFruitRows(stagingData.data.rows, estate_filter).length - eligibleRows.length,
    eligible_count: eligibleRows.length,
    row_limit: payload.row_limit ?? null,
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
  const requestedTabCount = payload.max_tabs || 10;
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

    // Step 7: Navigate each tab to the loosefruit page
    await Promise.all(pages.map(async (page, index) => {
      if (index > 0) await new Promise((resolve) => setTimeout(resolve, index * 1500));
      emit({ event: "loosefruit.multitab.tab.open.started", tab_index: index });
      try {
        await page.goto(getLoosefruitDetailUrl(loc_code), { waitUntil: "domcontentloaded", timeout: 45000 });
        await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
        emit({ event: "loosefruit.multitab.tab.ready", tab_index: index, url: page.url() });
      } catch (error) {
        emit({ event: "loosefruit.multitab.tab.open.failed", tab_index: index, message: error instanceof Error ? error.message : String(error) });
        throw error;
      }
    }));

    // Step 7: Process rows — run tabs SEQUENTIALLY to avoid ASP.NET postback overload
    // Each tab processes all its rows before the next tab starts
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
            if (text.match(/^A\d{4}$/)) empCodes.push(text);
          }
          return empCodes;
        });
        existing.forEach(code => existingEmpCodes.add(code));
      } catch (e) {
        // Ignore errors checking existing
      }
    }
    emit({ event: "loosefruit.multitab.check_existing.done", existing_count: existingEmpCodes.size });

    // Process tabs sequentially (one tab at a time) to avoid server overload
    for (let tabIdx = 0; tabIdx < pages.length; tabIdx++) {
      const page = pages[tabIdx];
      const assignment = assignments.find(a => a.tab_index === tabIdx);
      if (!assignment) continue;

      emit({ event: "loosefruit.multitab.tab.processing", tab_index: tabIdx, rows: assignment.rows.length });

      const tabRows: LoosefruitInputRowResult[] = [];
      const tabStats = { done: 0, skipped: 0, failed: 0, total: assignment.rows.length };

      for (let rowIndex = 0; rowIndex < assignment.rows.length; rowIndex++) {
        const row = assignment.rows[rowIndex];

        const normalizedEmpCode = row.emp_code.trim().toUpperCase();

        // Skip if already exists
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
          await page.waitForTimeout(200);
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
            // Check page health before starting row
            const alive = await ensurePageAlive(page, loc_code);
            if (!alive) {
              emit({ event: "loosefruit.multitab.row.reloading_dead_tab", tab_index: tabIdx, emp_code: row.emp_code });
            }

            // Reload page fresh — use "load" state for full DOM readiness
            const url = getLoosefruitDetailUrl(loc_code);
            await page.goto(url, { waitUntil: "load", timeout: 30000 }).catch((e) => {
              emit({ event: "loosefruit.multitab.tab.goto.failed", tab_index: tabIdx, url, error: String(e) });
            });

            // Wait for Add button to appear — indicates form is ready
            await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 }).catch(() => {});

            // Verify still alive after load
            const stillAlive = await ensurePageAlive(page, loc_code);
            if (!stillAlive) {
              if (attempt === 0) {
                emit({ event: "loosefruit.multitab.row.page_dead_after_load", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 });
                continue; // retry
              } else {
                tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page context dead after reload", tab_index: tabIdx });
                tabStats.failed += 1;
                break;
              }
            }

            // Set Charge To FIRST (reveals employee dropdown)
            await selectChargeTo(page, loc_code);
            await page.waitForTimeout(500);

            // Verify page still alive after postback
            const afterChargeAlive = await ensurePageAlive(page, loc_code);
            if (!afterChargeAlive) {
              if (attempt === 0) {
                emit({ event: "loosefruit.multitab.row.page_dead_after_charge", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 });
                continue;
              } else {
                tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page context dead after ChargeTo postback", tab_index: tabIdx });
                tabStats.failed += 1;
                break;
              }
            }

            // Set Transaction Date
            await setTransactionDate(page, doc_date);
            await page.waitForTimeout(300);

            // Verify page alive before selecting employee
            const beforeEmpAlive = await ensurePageAlive(page, loc_code);
            if (!beforeEmpAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_emp", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before emp select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            // Select employee (now visible after Charge To is set)
            await selectEmployee(page, row.emp_code);
            await page.waitForTimeout(500);

            // Verify page alive before task code
            const beforeTaskAlive = await ensurePageAlive(page, loc_code);
            if (!beforeTaskAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_task", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before task select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            // Select task code (triggers postback, reveals division/field dropdowns)
            await selectTaskCode(page, taskCode);
            await page.waitForTimeout(500);

            // Verify page alive before division code
            const beforeDivAlive = await ensurePageAlive(page, loc_code);
            if (!beforeDivAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_div", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before div select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            // Select division code (triggers postback, filters field options)
            await selectDivisionCode(page, divisionCode);
            await page.waitForTimeout(500);

            // Verify page alive before field select
            const beforeFieldAlive = await ensurePageAlive(page, loc_code);
            if (!beforeFieldAlive) {
              if (attempt === 0) { emit({ event: "loosefruit.multitab.row.page_dead_before_field", tab_index: tabIdx, emp_code: row.emp_code, attempt: attempt + 1 }); continue; }
              else { tabRows.push({ emp_code: row.emp_code, emp_name: row.emp_name, gang: row.gang, selisih: row.selisih, status: "failed", message: "Page dead before field select", tab_index: tabIdx }); tabStats.failed += 1; break; }
            }

            // Select field no code (no postback needed)
            await selectFieldNoCode(page, field_code);
            await page.waitForTimeout(300);

            // Select expense code (labour)
            await selectExpenseCode(page);
            await page.waitForTimeout(300);

            // Set MT and Rate
            await setMT(page, row.selisih);
            await setRate(page, rate);
            await page.waitForTimeout(200);

            // Click Add
            // Debug: dump form state right before click
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
            // Debug: check state right after add
            const afterState = await page.evaluate(() => {
              return {
                pageUrl: window.location.href,
                docIdDisabled: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.disabled,
                docId: (document.querySelector("#MainContent_txtDocID") as HTMLInputElement)?.value,
              };
            }).catch(e => ({ error: String(e) }));
            emit({ event: "loosefruit.multitab.row.post_add_state", tab_index: tabIdx, emp_code: row.emp_code, ...afterState });

            // Check result
            const finalDocId = await getDocumentId(page);
            if (finalDocId) {
              tabRows.push({
                emp_code: row.emp_code,
                emp_name: row.emp_name,
                gang: row.gang,
                selisih: row.selisih,
                status: "success",
                message: "Row added successfully",
                doc_id: finalDocId,
                mt: row.selisih,
                amount: row.selisih * rate,
                tab_index: tabIdx,
              });
              tabStats.done += 1;
              existingEmpCodes.add(row.emp_code);
              emit({ event: "loosefruit.multitab.row.success", tab_index: tabIdx, emp_code: row.emp_code, doc_id: finalDocId });
              success = true;
            } else {
              // Add failed — log and continue
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
        await page.waitForTimeout(200);
      }

      emit({ event: "loosefruit.multitab.tab.completed", tab_index: tabIdx, ...tabStats });
      rows.push(...tabRows);
    }

    emit({ event: "loosefruit.multitab.run.completed", total_processed: rows.length });

  } finally {
    await session.close();
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
