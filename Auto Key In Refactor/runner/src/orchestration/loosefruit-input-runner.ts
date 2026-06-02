/**
 * Loose Fruit Brondol Input Runner
 *
 * Orchestrates the input of selisih brondol data from staging-comparison API
 * into Plantware Loose Fruit Collector Details page.
 */

import type { RunPayload, RunResult, LoosefruitInputRowResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import {
  LoosefruitInputRow,
  fetchStagingComparison,
  filterLooseFruitRows,
  deriveDivisionFromGang,
  deriveTaskCodeFromLoc,
  getLoosefruitDetailUrl,
  selectEmployee,
  selectTaskCode,
  selectDivisionCode,
  selectFieldNoCode,
  setMT,
  setRate,
  clickAdd,
  getDocumentId,
} from "../plantware/loosefruit-input.js";

type Emit = (event: Record<string, unknown>) => void;

export async function runLoosefruitInput(
  payload: RunPayload,
  emit: Emit
): Promise<RunResult> {
  const started = new Date().toISOString();
  const staging_periode = payload.staging_periode ?? "2026-05";
  const loc_code = payload.loc_code ?? "P1A";
  const field_code = payload.field_code ?? "PM9601A1";
  const rate = payload.rate ?? 1750;
  const doc_date = payload.doc_date ?? "31/05/2026";
  const estate_filter = payload.estate_filter ?? undefined;
  const staging_source_url = payload.staging_source_url ?? undefined;
  const headless = payload.headless ?? false;

  const rows: LoosefruitInputRowResult[] = [];

  emit({
    event: "loosefruit.input.run.started",
    staging_periode,
    loc_code,
    rate,
    doc_date,
    estate_filter
  });

  // Step 1: Fetch staging comparison data
  emit({ event: "loosefruit.input.fetch.start", periode: staging_periode });
  const stagingData = await fetchStagingComparison(staging_periode, staging_source_url);
  if (!stagingData || !stagingData.data) {
    emit({ event: "loosefruit.input.fetch.failed", message: "Failed to fetch staging data" });
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
    event: "loosefruit.input.fetch.success",
    total_rows: stagingData.data.rows.length,
    total_selisih: stagingData.data.totals.selisih
  });

  // Step 2: Filter loose fruit employees (code starts with 'A') with positive selisih
  const filteredRows = filterLooseFruitRows(stagingData.data.rows, estate_filter);
  emit({ event: "loosefruit.input.filtered", filtered_count: filteredRows.length });

  if (filteredRows.length === 0) {
    emit({ event: "loosefruit.input.no_rows", message: "No rows with positive selisih to input" });
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

  // Step 3: Start browser session
  const session = new BrowserSession({
    headless,
    freshLoginFirst: false,
    loginFallback: true,
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

    // Step 4: Navigate to loosefruit detail page
    const page = await session.newPage();
    await page.goto(getLoosefruitDetailUrl(loc_code), { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#MainContent_btnAdd", { state: "visible", timeout: 15000 });
    emit({ event: "loosefruit.input.page.loaded", url: page.url() });

    // Step 5: Process each row
    for (let i = 0; i < filteredRows.length; i++) {
      const row = filteredRows[i];
      const taskCode = deriveTaskCodeFromLoc(loc_code);
      const divisionCode = deriveDivisionFromGang(row.gang);

      emit({
        event: "loosefruit.input.row.started",
        index: i + 1,
        total: filteredRows.length,
        emp_code: row.emp_code,
        gang: row.gang,
        selisih: row.selisih
      });

      try {
        // Check if employee already exists in the grid before adding
        const empAlreadyAdded = await page.evaluate((empCode: string) => {
          const grid = document.querySelector("#MainContent_grvDetail");
          if (!grid) return false;
          const cells = grid.querySelectorAll("td");
          for (const cell of cells) {
            if (cell.textContent?.trim() === empCode) return true;
          }
          return false;
        }, row.emp_code);

        if (empAlreadyAdded) {
          const existingDocId = await getDocumentId(page);
          rows.push({
            emp_code: row.emp_code,
            emp_name: row.emp_name,
            gang: row.gang,
            selisih: row.selisih,
            status: "skipped",
            message: "Employee already exists in document",
            doc_id: existingDocId,
            mt: row.selisih,
            amount: row.selisih * rate
          });
          emit({ event: "loosefruit.input.row.skipped", emp_code: row.emp_code });
          await page.waitForTimeout(300);
          continue;
        }

        // Select employee
        await selectEmployee(page, row.emp_code);
        await page.waitForTimeout(500);

        // Select task code
        await selectTaskCode(page, taskCode);
        await page.waitForTimeout(500);

        // Select division code
        await selectDivisionCode(page, divisionCode);
        await page.waitForTimeout(500);

        // Select field no code
        await selectFieldNoCode(page);
        await page.waitForTimeout(300);

        // Set MT and Rate
        await setMT(page, row.selisih);
        await setRate(page, rate);
        await page.waitForTimeout(300);

        // Click Add
        await clickAdd(page);

        // Check result
        const finalDocId = await getDocumentId(page);
        const finalRate = rate;
        if (finalDocId) {
          rows.push({
            emp_code: row.emp_code,
            emp_name: row.emp_name,
            gang: row.gang,
            selisih: row.selisih,
            status: "success",
            message: "Row added successfully",
            doc_id: finalDocId,
            mt: row.selisih,
            amount: row.selisih * finalRate
          });
        } else {
          rows.push({
            emp_code: row.emp_code,
            emp_name: row.emp_name,
            gang: row.gang,
            selisih: row.selisih,
            status: "failed",
            message: "Document ID not generated after Add"
          });
        }
      } catch (error) {
        rows.push({
          emp_code: row.emp_code,
          emp_name: row.emp_name,
          gang: row.gang,
          selisih: row.selisih,
          status: "failed",
          message: error instanceof Error ? error.message : String(error)
        });
      }

      // Small delay between rows
      await page.waitForTimeout(300);
    }

    emit({ event: "loosefruit.input.run.completed", processed: rows.length });

  } finally {
    await session.close();
  }

  const successRows = rows.filter(r => r.status === "success").length;
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
    skipped_existing_rows: 0,
    failed_rows: failedRows,
    error_summary: failedRows > 0 ? `${failedRows} rows failed` : null,
    rows
  };
}
