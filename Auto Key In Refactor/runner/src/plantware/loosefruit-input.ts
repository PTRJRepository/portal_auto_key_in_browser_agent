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
  const field = page.locator("#MainContent_txtMT");
  await field.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await field.fill(String(mt));
}

export async function setRate(page: Page, rate: number): Promise<void> {
  const field = page.locator("#MainContent_txtRate");
  await field.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await field.fill(String(rate));
}

export async function clickAdd(page: Page, screenshotLabel?: string): Promise<void> {
  // Wait for postback from previous field selection to fully settle
  try {
    await page.waitForLoadState("load", { timeout: 15000 });
    await safeWait(page, 600);
  } catch {
    await safeWait(page, 2000);
  }

  if (screenshotLabel) {
    await page.screenshot({ path: screenshotLabel });
  }

  // Wait for Add button to be enabled (not disabled during postback)
  try {
    await page.waitForFunction(
      () => {
        const btn = document.querySelector("#MainContent_btnAdd") as HTMLInputElement | null;
        return btn && !btn.disabled && btn.offsetParent !== null;
      },
      { timeout: 8000 }
    );
  } catch {
    // Button might not be found or visible; proceed anyway
  }

  // Use native .click() — more reliable than manual onclick handler injection
  // which can fail when handler is null or when ASP.NET postback is in progress
  const btn = page.locator("#MainContent_btnAdd");
  await btn.click({ force: true, timeout: 5000 });

  // Wait for ASP.NET postback to complete and DOM to settle
  try {
    await page.waitForLoadState("load", { timeout: 25000 });
    await safeWait(page, 1000);
  } catch {
    // If load state fails (e.g. page navigated), give a fixed buffer
    await safeWait(page, 3000);
  }

  // Verify Add button is back (not permanently disabled = postback completed)
  try {
    await page.waitForFunction(
      () => {
        const b = document.querySelector("#MainContent_btnAdd") as HTMLInputElement | null;
        return b && !b.disabled;
      },
      { timeout: 10000 }
    );
  } catch {
    // Button still disabled — may indicate validation error or postback failure
  }
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

export function deriveDivisionFromGang(gang: string): string {
  return gang.length >= 2 ? gang.slice(0, 2).toUpperCase() : gang.toUpperCase();
}

export function deriveTaskCodeFromLoc(locCode: string): string {
  return `CT2202${locCode}`;
}

export interface StagingComparisonRow {
  emp_code: string; emp_name: string; gang: string; gang_name: string;
  divisi: string; estate: string; staging_brondol: number; plantware_brondol: number; selisih: number;
}

export interface StagingComparisonResponse {
  success: boolean;
  data: { month: number; year: number; periode: string; count: number;
    totals: { staging_brondol: number; plantware_brondol: number; selisih: number };
    rows: StagingComparisonRow[]; };
}

function frontendToBackendSource(source: string): string {
  if (source.endsWith("/upah/staging-comparison") && source.includes(":3001")) {
    return source.replace("http://localhost:3001", "http://10.0.0.128:8002").replace(":3001", ":8002").replace("/upah/staging-comparison", "/backend/upah/api/staging/staging-comparison");
  }
  return source;
}

export function buildStagingComparisonUrl(source: string | null | undefined, periode: string, division?: string | null, gang?: string | null): string {
  let rawSource = frontendToBackendSource((source || process.env.AUTO_KEY_IN_LOOSEFRUIT_STAGING_SOURCE || "http://10.0.0.128:8002").trim().replace(/\/+$/, ""));
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
    const response = await fetch(buildStagingComparisonUrl(source, periode, division, gang));
    if (!response.ok) return null;
    return await response.json() as StagingComparisonResponse;
  } catch {
    return null;
  }
}

export function normalizeStagingComparisonRows(rows: StagingComparisonRow[]): StagingComparisonRow[] {
  return rows.map(row => ({
    ...row,
    emp_code: String(row.emp_code || "").trim().toUpperCase(),
    gang: String(row.gang || (row as any).gang_code || "").trim().toUpperCase(),
    estate: String(row.estate || (row as any).loc_code || (row as any).division || "").trim().toUpperCase(),
    staging_brondol: Number(row.staging_brondol ?? (row as any).staging_bunches ?? 0),
    plantware_brondol: Number(row.plantware_brondol ?? (row as any).prod_mt ?? 0),
    selisih: Number(row.selisih ?? (row as any).delta ?? 0),
  }));
}

export function filterLooseFruitRows(rows: StagingComparisonRow[], estate?: string): StagingComparisonRow[] {
  const estateFilter = (estate || "").trim().toUpperCase();
  return normalizeStagingComparisonRows(rows).filter(row => row.selisih > 0 && !!row.emp_code && (!estateFilter || row.estate === estateFilter));
}

export function groupByGang(rows: StagingComparisonRow[]): Map<string, StagingComparisonRow[]> {
  const groups = new Map<string, StagingComparisonRow[]>();
  for (const row of rows) {
    if (!groups.has(row.gang)) groups.set(row.gang, []);
    groups.get(row.gang)!.push(row);
  }
  return groups;
}