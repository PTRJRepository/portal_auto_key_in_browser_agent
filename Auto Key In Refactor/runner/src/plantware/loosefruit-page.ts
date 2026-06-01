import type { Locator, Page } from "playwright";
import { PLANTWARE_CONFIG } from "../config.js";
import type { LoosefruitTarget } from "../types.js";

export interface LoosefruitRow {
  docId: string;
  masterId: string;
  locCode: string;
  docDate: string;
  status: string;
  totalMt: string;
}

export const loosefruitListUrl = PLANTWARE_CONFIG.baseUrl + "/en/PR/trx/frmPrTrxLooseFruitList.aspx";
const LIST_READY_SELECTOR = "#MainContent_gvLine, a[href*='frmPrTrxLooseFruitDet']";
const SEARCH_INPUT_SELECTOR = "#MainContent_txtDocID";
const SEARCH_BUTTON_SELECTOR = "#MainContent_btnSearch";
const DELETE_BUTTON_SELECTORS = [
  "#MainContent_btnDelete",
  "input[id$='btnDelete']",
  "button:has-text('Delete')",
  "input[value='Delete']",
  "input[value='Hapus']",
  "button:has-text('Hapus')"
];

export async function gotoLoosefruitListPage(page: Page): Promise<void> {
  await gotoPage(page, loosefruitListUrl);
  await assertLoosefruitListPage(page);
}

export async function visibleLoosefruitRows(page: Page): Promise<LoosefruitRow[]> {
  return page.locator("#MainContent_gvLine tr").evaluateAll((rows) => {
    const results: LoosefruitRow[] = [];
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll("td"));
      const link = cells[0]?.querySelector("a[href*='MasterID=']") as HTMLAnchorElement | null;
      const docId = link?.textContent?.trim() ?? "";
      if (!docId) continue;
      const masterId = new URL(link?.href ?? "", window.location.href).searchParams.get("MasterID") ?? "";
      results.push({
        docId,
        masterId,
        locCode: cells[1]?.textContent?.trim() ?? "",
        docDate: cells[2]?.textContent?.trim() ?? "",
        status: cells[3]?.textContent?.trim() ?? "",
        totalMt: cells[4]?.textContent?.trim() ?? ""
      });
    }
    return results;
  });
}

export async function searchLoosefruitByDocId(page: Page, target: LoosefruitTarget): Promise<LoosefruitRow | null> {
  const searchInput = page.locator(SEARCH_INPUT_SELECTOR);
  const searchVisible = await searchInput.isVisible({ timeout: 3000 }).catch(() => false);
  if (!searchVisible) {
    throw new Error("Search input #MainContent_txtDocID not visible on loosefruit list page");
  }
  await searchInput.fill("");
  await searchInput.fill(target.doc_id);
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    page.locator(SEARCH_BUTTON_SELECTOR).click({ noWaitAfter: true })
  ]);
  await assertLoosefruitListPage(page);
  const rows = await visibleLoosefruitRows(page);
  return rows.find((row) => normalizeDocId(row.docId) === normalizeDocId(target.doc_id)) ?? null;
}

export async function deleteLoosefruitDocId(
  page: Page,
  target: LoosefruitTarget,
  debug: (event: Record<string, unknown>) => void = () => {}
): Promise<void> {
  const link = await loosefruitDetailLink(page, target);
  debug({ step: "detail.click.before", doc_id: target.doc_id, current_url: page.url(), target });
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    link.click({ noWaitAfter: true })
  ]);
  debug({ step: "detail.click.after", current_url: page.url(), target });
  const detailProof = await assertLoosefruitDetailMatches(page, target);
  debug({ step: "detail.validation.passed", ...detailProof, target });

  const deleteButton = await lastVisibleLocator(page, DELETE_BUTTON_SELECTORS);
  if (!deleteButton) {
    throw new Error("Delete button not found on loosefruit detail page for " + target.doc_id);
  }
  debug({ step: "delete.button.visible", current_url: page.url(), target });
  page.once("dialog", async (dialog) => {
    debug({ step: "delete.dialog", dialog_type: dialog.type(), dialog_message: dialog.message(), target });
    await dialog.accept();
  });
  await Promise.all([
    page.waitForURL(/frmPrTrxLooseFruitList/i, { timeout: 30000 }).catch(() => {}),
    deleteButton.click({ noWaitAfter: true })
  ]);
  debug({ step: "delete.click.after", current_url: page.url(), target });
}

export async function assertLoosefruitListPage(page: Page): Promise<void> {
  const url = page.url();
  if (/login|SessionExpire/i.test(url)) throw new Error("Not authenticated on Plantware loosefruit list page: " + url);
  await page.locator(LIST_READY_SELECTOR).first().waitFor({ state: "visible", timeout: 15000 });
}

async function loosefruitDetailLink(page: Page, target: LoosefruitTarget): Promise<Locator> {
  const link = target.master_id
    ? page.locator("a[href*='MasterID=" + target.master_id + "'][href*='frmPrTrxLooseFruitDet']").first()
    : page.locator("a[href*='MasterID='][href*='frmPrTrxLooseFruitDet']").filter({ hasText: target.doc_id }).first();
  const visible = await link.isVisible({ timeout: 3000 }).catch(() => false);
  if (!visible) {
    throw new Error("Loosefruit detail link not found for DocID " + target.doc_id);
  }
  return link;
}

async function assertLoosefruitDetailMatches(page: Page, target: LoosefruitTarget): Promise<Record<string, unknown>> {
  await page.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => {});
  await page.waitForURL(/frmPrTrxLooseFruitDet/i, { timeout: 15000 });
  const url = page.url();
  const actualMasterId = new URL(url).searchParams.get("MasterID") ?? "";
  if (target.master_id && actualMasterId !== target.master_id) {
    throw new Error("Loosefruit detail MasterID mismatch for " + target.doc_id + ": " + url);
  }
  const rawBodyText = (await page.locator("body").textContent({ timeout: 5000 }).catch(() => "")) ?? "";
  const bodyText = normalizeText(rawBodyText);
  if (!target.master_id && !bodyText.includes(normalizeText(target.doc_id))) {
    throw new Error("Loosefruit detail page does not contain DocID " + target.doc_id);
  }
  const locCode = String(target.loc_code ?? "").trim();
  if (locCode && bodyText.includes("LOCCODE") && !bodyText.includes(normalizeText(locCode))) {
    throw new Error("Loosefruit detail page does not contain LocCode " + locCode + " for " + target.doc_id);
  }
  return {
    current_url: url,
    actual_master_id: actualMasterId,
    body_snippet: rawBodyText.replace(/\s+/g, " ").trim().slice(0, 500),
    delete_button_visible: Boolean(await lastVisibleLocator(page, DELETE_BUTTON_SELECTORS))
  };
}

async function lastVisibleLocator(page: Page, selectors: string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = await locator.count().catch(() => 0);
    for (let index = count - 1; index >= 0; index -= 1) {
      const item = locator.nth(index);
      if (await item.isVisible({ timeout: 500 }).catch(() => false)) return item;
    }
  }
  return null;
}

function normalizeDocId(value: string): string {
  return value.replace(/\s+/g, "").trim().toUpperCase();
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toUpperCase();
}

async function gotoPage(page: Page, url: string): Promise<void> {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const transient = /ERR_ABORTED|Navigation interrupted|Timeout/i.test(message);
      if (!transient || attempt === 3) throw error;
      await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
    }
  }
}
