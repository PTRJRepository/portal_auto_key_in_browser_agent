/**
 * Loose Fruit Brondol Input Runner
 *
 * Reads selisih (difference) data from staging-comparison API and inputs
 * into Plantware Loose Fruit Collector Details page.
 *
 * Data source: configurable staging-comparison endpoint
 * Target page: http://plantwarep3:8001/en/PR/trx/frmPrTrxLooseFruitDet.aspx
 */

import type { Page } from "playwright";
import * as fs from "node:fs";

export interface LoosefruitInputRow {
  emp_code: string;
  emp_name: string;
  gang: string;
  gang_name: string;
  divisi: string;
  estate: string;
  staging_brondol: number;
  plantware_brondol: number;
  selisih: number;
}

async function safeWait(page: Page, ms: number): Promise<void> {
  await page.waitForTimeout(ms).catch(() => {});
}

export interface LoosefruitInputResult {
  emp_code: string;
  status: "success" | "failed" | "skipped";
  message: string;
  doc_id?: string;
  mt?: number;
  amount?: number;
}

export function getLoosefruitDetailUrl(locCode: string): string {
  const base = process.env.PLANTWARE_BASE_URL ?? "http://plantwarep3:8001";
  return `${base}/en/PR/trx/frmPrTrxLooseFruitDet.aspx`;
}

export async function waitForPostback(page: Page): Promise<void> {
  // Wait for ASP.NET postback to complete and DOM to settle.
  // Strategy: wait for load state (reliable for full page reloads) + small buffer.
  try {
    await page.waitForLoadState("load", { timeout: 20000 });
    await safeWait(page, 800);
  } catch {
    // Page may have navigated or context closed — give a fixed buffer as fallback
    await safeWait(page, 3000);
  }
}

export async function waitForStable(page: Page): Promise<void> {
  // Use load state for reliability, fall back to timeout if page is unstable
  try {
    await page.waitForLoadState("load", { timeout: 10000 });
  } catch {
    await safeWait(page, 2000);
  }
}


async function changeSelectValue(page: Page, selector: string, value: string, waitPostback: boolean): Promise<void> {
  try {
    await page.evaluate(({ selector, value }) => {
      const el = document.querySelector(selector) as HTMLSelectElement | null;
      if (!el) throw new Error(`Select not found: ${selector}`);
      el.value = value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, { selector, value });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!/Execution context was destroyed|Target page, context or browser has been closed|navigation/i.test(message)) {
      throw error;
    }
  }
  if (waitPostback) {
    await waitForPostback(page);
  } else {
    await safeWait(page, 300);
  }
}

export async function ensurePageAlive(page: Page, urlHint: string): Promise<boolean> {
  try {
    const url = page.url();
    if (!url || url === "about:blank") return false;
    if (url.includes("javascript") || url.includes("__doPostBack")) return false;
    // Verify main content area exists
    await page.waitForSelector("#MainContent_btnAdd", { state: "attached", timeout: 3000 }).catch(() => null);
    return true;
  } catch {
    return false;
  }
}

export async function selectChargeTo(page: Page, locCode: string): Promise<void> {
  await changeSelectValue(page, "#MainContent_ddlChargeTo", locCode, true);
}

export async function setTransactionDate(page: Page, date: string): Promise<void> {
  const field = page.locator("#MainContent_txtTrxDate");
  await field.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await field.fill(date);
}

export async function selectEmployee(page: Page, empCode: string): Promise<void> {
  await changeSelectValue(page, "#MainContent_ddlEmployee", empCode, true);
}

export async function selectTaskCode(page: Page, taskCode: string): Promise<void> {
  await changeSelectValue(page, "#MainContent_ddlTaskCode", taskCode, true);
}

export async function selectDivisionCode(page: Page, divisionCode: string): Promise<void> {
  await changeSelectValue(page, "#MainContent_MultiDimAcc_ddlBlock", divisionCode, true);
}

export async function selectExpenseCode(page: Page): Promise<void> {
  await page.evaluate(() => {
    const select = document.querySelector("#MainContent_MultiDimAcc_ddlExpCode") as HTMLSelectElement | null;
    if (!select) return;
    const options = Array.from(select.options);
    const labour = options.find(o => o.text.toUpperCase().includes("LABOUR"));
    const bebas = options.find(o => o.text.toLowerCase().includes("bebas"));
    select.value = (labour || bebas || options[1] || options[0])?.value || "";
  });
  await safeWait(page, 300);
}

export async function selectFieldNoCode(page: Page, fieldCode?: string | null): Promise<void> {
  await safeWait(page, 1200);
  const options = await page.evaluate(() => {
    const select = document.querySelector("#MainContent_MultiDimAcc_ddlSubBlk") as HTMLSelectElement | null;
    if (!select) return [];
    return Array.from(select.options).map((opt: HTMLOptionElement) => ({
      value: opt.value,
      text: opt.text.trim()
    }));
  });
  if (options.length > 1) {
    const requested = (fieldCode || "").trim().toUpperCase();
    const bebas = options.find(o => o.text.toLowerCase().includes("bebas"));
    const exact = requested ? options.find(o => o.value.toUpperCase() === requested || o.text.toUpperCase().includes(requested)) : undefined;
    const target = exact || bebas || options[1];
    await page.evaluate((val: string) => {
      const select = document.querySelector("#MainContent_MultiDimAcc_ddlSubBlk") as HTMLSelectElement | null;
      if (!select) return;
      select.value = val;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }, target.value);
  }
  await safeWait(page, 200);
}

export async function setMT(page: Page, mt: number): Promise<void> {
  const value = String(mt);
  // Only use .fill() - don't dispatch change events to avoid ASP.NET postback
  const field = page.locator("#MainContent_txtMT");
  await field.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await field.fill(value);
  // Also set Total MT (hidden field that Plantware may use)
  await page.evaluate((val) => {
    const total = document.querySelector("#MainContent_txtTotalMT") as HTMLInputElement | null;
    if (total) {
      total.value = val;
      total.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }, value).catch(() => {});
}

export async function setRate(page: Page, rate: number): Promise<void> {
  const value = String(rate);
  const field = page.locator("#MainContent_txtRate");
  await field.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await field.fill(value);
  await field.press("Tab").catch(() => {});
  await page.evaluate((val) => {
    const input = document.querySelector("#MainContent_txtRate") as HTMLInputElement | null;
    if (!input) return;
    input.value = val;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new Event("blur", { bubbles: true }));
  }, value).catch(() => {});
  await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1000);
}

export async function waitForAmountNonZero(page: Page, timeout = 10000): Promise<number> {
  const amountSelectors = [
    "#MainContent_lblTotalAmount",
    "span[id$='lblTotalAmount']",
    "#MainContent_txtAmount",
    "#MainContent_txtAmt",
    "input[id$='txtAmount']",
    "input[id$='txtAmt']",
  ];
  const readAmount = (selectors: string[]) => {
    const parseAmount = (value: string) => Number(String(value || "").replace(/,/g, ""));
    for (const selector of selectors) {
      const field = document.querySelector(selector) as HTMLInputElement | HTMLElement | null;
      if (!field) continue;
      const value = field instanceof HTMLInputElement ? field.value : field.textContent || "";
      const amount = parseAmount(value);
      if (Number.isFinite(amount) && amount > 0) return amount;
    }
    return 0;
  };
  await page.waitForFunction((selectors: string[]) => {
    const parseAmount = (value: string) => Number(String(value || "").replace(/,/g, ""));
    for (const selector of selectors) {
      const field = document.querySelector(selector) as HTMLInputElement | HTMLElement | null;
      if (!field) continue;
      const value = field instanceof HTMLInputElement ? field.value : field.textContent || "";
      const amount = parseAmount(value);
      if (Number.isFinite(amount) && amount > 0) return true;
    }
    return false;
  }, amountSelectors, { timeout });
  const amount = await page.evaluate(readAmount, amountSelectors);
  if (!amount) throw new Error("Amount remains zero after Rate input");
  return amount;
}

export async function clickAdd(page: Page, screenshotLabel?: string): Promise<void> {
  // Wait for any previous postback to fully settle before clicking
  await safeWait(page, 1000);

  if (screenshotLabel) {
    await page.screenshot({ path: screenshotLabel });
  }

  // Wait for Add button to be enabled (not disabled during postback)
  await page.waitForFunction(
    () => {
      const btn = document.querySelector("#MainContent_btnAdd") as HTMLInputElement | null;
      return btn && !btn.disabled && btn.offsetParent !== null;
    },
    { timeout: 8000 }
  ).catch(() => {});

  if (screenshotLabel) {
    await page.screenshot({ path: screenshotLabel.replace("pre-add", "pre-add-btn-ready") });
  }

  // Click immediately when button is ready
  await page.click("#MainContent_btnAdd", { timeout: 5000 });

  // Wait for ASP.NET postback to fully complete and grid to render
  // Plantware reloads the grid after Add — give it time to render the new row
  await page.waitForLoadState("load", { timeout: 25000 }).catch(() => {});
  await safeWait(page, 5000);

  // Verify Add button is back and enabled (confirms postback completed successfully)
  await page.waitForFunction(
    () => {
      const btn = document.querySelector("#MainContent_btnAdd") as HTMLInputElement | null;
      return btn && !btn.disabled;
    },
    { timeout: 15000 }
  ).catch(() => {});
}

export async function getDocumentId(page: Page): Promise<string | null> {
  try {
    const docIdCell = page.locator("#MainContent_txtDocID");
    const isDisabled = await docIdCell.isDisabled();
    if (isDisabled) return await docIdCell.inputValue();
    return null;
  } catch {
    return null;
  }
}

/**
 * Check if employee was successfully added to the grid.
 * After clicking Add, the employee code should appear in the grid.
 */
export async function isEmployeeAddedToGrid(page: Page, empCode: string): Promise<{ added: boolean; docId: string | null }> {
  try {
    const result = await page.evaluate((code) => {
      const grid = document.querySelector("#MainContent_grvDetail");
      if (!grid) return { added: false, docId: null };
      const cells = grid.querySelectorAll("td");
      let found = false;
      let docId: string | null = null;
      // Scan grid cells for emp code
      for (const cell of cells) {
        if (cell.textContent?.trim() === code) {
          found = true;
          break;
        }
      }
      // Also get docId from input field (if it has a value now)
      const docIdField = document.querySelector("#MainContent_txtDocID") as HTMLInputElement | null;
      if (docIdField && !docIdField.disabled && docIdField.value) {
        docId = docIdField.value;
      }
      return { added: found, docId };
    }, empCode.trim().toUpperCase());
    return result;
  } catch {
    return { added: false, docId: null };
  }
}

export function deriveDivisionFromGang(gang: string): string {
  return gang.length >= 2 ? gang.slice(0, 2).toUpperCase() : gang.toUpperCase();
}

export function deriveTaskCodeFromLoc(locCode: string): string {
  return `CT2202${locCode}`;
}

export interface StagingComparisonRow {
  emp_code: string; emp_name: string; gang: string; gang_name: string;
  divisi: string; estate: string; staging_brondol: number; plantware_brondol: number; selisih: number; status?: string;
}

export interface StagingComparisonResponse {
  success: boolean;
  data: { month: number; year: number; periode: string; count: number;
    totals: { staging_brondol: number; plantware_brondol: number; selisih: number };
    rows: StagingComparisonRow[]; };
}


function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index++) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      cells.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current);
  return cells;
}

function numericCsvValue(value: string | undefined): number {
  const normalized = String(value ?? "").trim().replace(/,/g, "");
  if (!normalized) return 0;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function loadStagingComparisonFromCsv(csvPath: string, periode = ""): StagingComparisonResponse {
  const path = csvPath.trim().replace(/^"|"$/g, "");
  const content = fs.readFileSync(path, "utf-8").replace(/^﻿/, "");
  const lines = content.split(/\r?\n/).filter(line => line.trim());
  if (lines.length === 0) throw new Error(`Loosefruit CSV is empty: ${path}`);
  const headers = parseCsvLine(lines[0]).map(header => header.trim());
  const rows: StagingComparisonRow[] = [];
  for (const line of lines.slice(1)) {
    const cells = parseCsvLine(line);
    const row: Record<string, string> = {};
    headers.forEach((header, index) => { row[header] = cells[index] ?? ""; });
    const empCode = String(row.EmpCode || row.emp_code || "").trim().toUpperCase();
    const division = String(row.Div || row.division || row.estate || "").trim().toUpperCase();
    if (!empCode || !division) continue;
    const stagingBrondol = numericCsvValue(row.TotalS);
    const plantwareBrondol = numericCsvValue(row.TotalP);
    const selisih = Number((stagingBrondol - plantwareBrondol).toFixed(2));
    rows.push({
      emp_code: empCode,
      emp_name: String(row.Nama || row.emp_name || "").trim(),
      gang: String(row.Gang || row.gang || "").trim().toUpperCase(),
      gang_name: "",
      divisi: division,
      estate: division,
      staging_brondol: stagingBrondol,
      plantware_brondol: plantwareBrondol,
      selisih,
      status: Math.abs(selisih) <= 0.01 ? "match" : (selisih > 0 ? "diff" : "plantware_more"),
    });
  }
  const totals = rows.reduce((acc, row) => {
    acc.staging_brondol += row.staging_brondol;
    acc.plantware_brondol += row.plantware_brondol;
    acc.selisih += row.selisih;
    return acc;
  }, { staging_brondol: 0, plantware_brondol: 0, selisih: 0 });
  totals.staging_brondol = Number(totals.staging_brondol.toFixed(2));
  totals.plantware_brondol = Number(totals.plantware_brondol.toFixed(2));
  totals.selisih = Number(totals.selisih.toFixed(2));
  const [year, month] = periode.split("-").map(value => Number(value));
  return {
    success: true,
    data: {
      month: month || 0,
      year: year || 0,
      periode,
      count: rows.length,
      totals,
      rows,
    },
  };
}

function isCsvSource(source: string | null | undefined): boolean {
  return !!source && source.trim().toLowerCase().endsWith(".csv");
}

function frontendToBackendSource(source: string): string {
  if (source.endsWith("/upah/staging-comparison") && source.includes(":3001")) {
    return source.replace("http://localhost:3001", "http://10.0.0.128:8002").replace(":3001", ":8002").replace("/upah/staging-comparison", "/backend/upah/api/staging/staging-comparison");
  }
  return source;
}

export function buildStagingComparisonUrl(source: string | null | undefined, periode: string, division?: string | null, gang?: string | null): string {
  let rawSource = frontendToBackendSource((source || process.env.AUTO_KEY_IN_LOOSEFRUIT_STAGING_SOURCE || "C:/Users/nbgmf/Downloads/pivot_loosefruit_5_2026 (1).csv").trim().replace(/\/+$/, ""));
  const params = new URLSearchParams({ periode });
  if (division) params.set("division", division.trim().toUpperCase());
  if (gang) params.set("gang", gang.trim().toUpperCase());
  if (rawSource.endsWith("/upah/staging-comparison")) {
    rawSource = rawSource.replace("/upah/staging-comparison", "/backend/upah/api/staging/staging-comparison");
  }
  if (rawSource.endsWith("/api/staging/staging-comparison") || rawSource.endsWith("/backend/upah/api/staging/staging-comparison")) {
    return `${rawSource}?${params.toString()}`;
  }
  return `${rawSource}/backend/upah/api/staging/staging-comparison?${params.toString()}`;
}

export async function fetchStagingComparison(periode: string, source?: string | null, division?: string | null, gang?: string | null): Promise<StagingComparisonResponse | null> {
  try {
    if (isCsvSource(source)) return loadStagingComparisonFromCsv(source || "", periode);
    const response = await fetch(buildStagingComparisonUrl(source, periode, division, gang));
    if (!response.ok) return null;
    return await response.json() as StagingComparisonResponse;
  } catch {
    return null;
  }
}

export function normalizeStagingComparisonRows(rows: StagingComparisonRow[]): StagingComparisonRow[] {
  return rows.map(row => {
    const stagingBrondol = Number(row.staging_brondol ?? (row as any).staging_bunches ?? 0);
    const plantwareBrondol = Number(row.plantware_brondol ?? (row as any).prod_mt ?? 0);
    const rawDelta = row.selisih ?? (row as any).delta;
    let selisih = rawDelta === undefined || rawDelta === null ? Number((stagingBrondol - plantwareBrondol).toFixed(2)) : Number(rawDelta || 0);
    if (Math.abs((stagingBrondol - plantwareBrondol) - selisih) > 0.01) {
      selisih = Number((stagingBrondol - plantwareBrondol).toFixed(2));
    }
    return {
      ...row,
      emp_code: String(row.emp_code || "").trim().toUpperCase(),
      gang: String(row.gang || (row as any).gang_code || "").trim().toUpperCase(),
      estate: String(row.estate || (row as any).loc_code || (row as any).division || "").trim().toUpperCase(),
      staging_brondol: stagingBrondol,
      plantware_brondol: plantwareBrondol,
      selisih,
      status: String((row as any).status || "").trim().toLowerCase(),
    };
  });
}

export function isLoosefruitInputNeeded(row: StagingComparisonRow): boolean {
  return row.selisih > 0.01 && !!row.emp_code && row.status !== "match" && row.staging_brondol > row.plantware_brondol + 0.01;
}

export function filterLooseFruitRows(rows: StagingComparisonRow[], estate?: string): StagingComparisonRow[] {
  const estateFilter = (estate || "").trim().toUpperCase();
  return normalizeStagingComparisonRows(rows).filter(row => isLoosefruitInputNeeded(row) && (!estateFilter || row.estate === estateFilter));
}

export function groupByGang(rows: StagingComparisonRow[]): Map<string, StagingComparisonRow[]> {
  const groups = new Map<string, StagingComparisonRow[]>();
  for (const row of rows) {
    if (!groups.has(row.gang)) groups.set(row.gang, []);
    groups.get(row.gang)!.push(row);
  }
  return groups;
}
