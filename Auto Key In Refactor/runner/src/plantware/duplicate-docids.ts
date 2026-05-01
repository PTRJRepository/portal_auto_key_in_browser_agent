import type { Page } from "playwright";
import { PLANTWARE_CONFIG } from "../config.js";
import type { DuplicateDocIdTarget } from "../types.js";

export interface FoundDocId {
  docId: string;
  pageIndex: number;
}

const listUrl = `${PLANTWARE_CONFIG.baseUrl}${PLANTWARE_CONFIG.listPage}`;

export async function gotoListPage(page: Page): Promise<void> {
  await gotoPage(page, listUrl);
  await assertListPage(page);
}

export interface VisibleDocumentRow {
  docId: string;
  masterId: string;
  empCode: string;
  docDesc: string;
}

export async function visibleDocumentRows(page: Page): Promise<VisibleDocumentRow[]> {
  return page.locator("#MainContent_gvLine tr").evaluateAll((rows) => {
    const results: VisibleDocumentRow[] = [];
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll("td"));
      const link = cells[0]?.querySelector("a[href*='MasterID=']") as HTMLAnchorElement | null;
      const docId = link?.textContent?.trim() ?? "";
      if (!docId) continue;
      const masterId = new URL(link?.href ?? "", window.location.href).searchParams.get("MasterID") ?? "";
      results.push({
        docId,
        masterId,
        empCode: cells[2]?.textContent?.trim() ?? "",
        docDesc: cells[4]?.textContent?.trim() ?? ""
      });
    }
    return results;
  });
}

export async function visibleDocumentIds(page: Page): Promise<string[]> {
  return (await visibleDocumentRows(page)).map((row) => row.docId);
}

export function normalizeDocId(value: string): string {
  return value.replace(/\s+/g, "").trim().toUpperCase();
}

export function targetKey(target: DuplicateDocIdTarget): string {
  return target.master_id ? `MASTER:${target.master_id.trim()}` : `DOC:${normalizeDocId(target.doc_id)}`;
}

export interface VisibleTargetMatch {
  key: string;
  row: VisibleDocumentRow;
}

export async function findVisibleTargetMatches(page: Page, targets: Set<string>): Promise<VisibleTargetMatch[]> {
  const visibleRows = await visibleDocumentRows(page);
  return visibleRows.flatMap((row) => {
    const masterKey = `MASTER:${row.masterId.trim()}`;
    const docKey = `DOC:${normalizeDocId(row.docId)}`;
    if (targets.has(masterKey)) return [{ key: masterKey, row }];
    if (targets.has(docKey)) return [{ key: docKey, row }];
    return [];
  });
}

export async function findVisibleTargets(page: Page, targets: Set<string>): Promise<string[]> {
  return (await findVisibleTargetMatches(page, targets)).map((match) => match.key);
}

export async function findVisibleTarget(page: Page, targets: Set<string>): Promise<string | null> {
  return (await findVisibleTargets(page, targets))[0] ?? null;
}

export async function searchVisibleTargetByDocId(page: Page, target: DuplicateDocIdTarget): Promise<VisibleTargetMatch | null> {
  const searchInput = page.locator("#MainContent_txtDocID");
  const searchVisible = await searchInput.isVisible({ timeout: 1000 }).catch(() => false);
  if (!searchVisible) return null;
  await searchInput.fill(target.doc_id);
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    page.locator("#MainContent_btnSearch").click({ noWaitAfter: true })
  ]);
  await assertListPage(page);
  const keys = new Set([targetKey(target), `DOC:${normalizeDocId(target.doc_id)}`]);
  return (await findVisibleTargetMatches(page, keys))[0] ?? null;
}

export async function goToNextListPage(page: Page): Promise<boolean> {
  const beforeSignature = await listPageSignature(page);
  const nextButton = page.locator("#MainContent_btnNext");
  const nextVisible = await nextButton.isVisible({ timeout: 1000 }).catch(() => false);
  const nextEnabled = nextVisible && await nextButton.isEnabled().catch(() => false);
  if (!nextEnabled) return false;
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    nextButton.click({ noWaitAfter: true })
  ]);
  await assertListPage(page);
  const afterSignature = await listPageSignature(page);
  return afterSignature !== beforeSignature;
}

export async function deleteVisibleDocId(page: Page, target: DuplicateDocIdTarget, debug: (event: Record<string, unknown>) => void = () => {}): Promise<void> {
  const selector = target.master_id ? `a[href*='MasterID=${target.master_id}']` : `link:${target.doc_id}`;
  const link = target.master_id
    ? page.locator(`a[href*='MasterID=${target.master_id}']`).first()
    : page.getByRole("link", { name: target.doc_id, exact: true });
  debug({ step: "detail.click.before", selector, current_url: page.url(), target });
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    link.click()
  ]);
  debug({ step: "detail.click.after", current_url: page.url(), target });
  const detailProof = await assertDuplicateDetailMatches(page, target);
  debug({ step: "detail.validation.passed", ...detailProof, target });
  await page.locator("#MainContent_btnDelete").waitFor({ state: "visible", timeout: 15000 });
  debug({ step: "delete.button.visible", current_url: page.url(), target });
  page.once("dialog", async (dialog) => {
    debug({ step: "delete.dialog", dialog_type: dialog.type(), dialog_message: dialog.message(), target });
    await dialog.accept();
  });
  await Promise.all([
    page.waitForURL(/frmPrTrxADLists/i, { timeout: 30000 }).catch(() => {}),
    page.locator("#MainContent_btnDelete").click({ noWaitAfter: true })
  ]);
  debug({ step: "delete.click.after", current_url: page.url(), target });
}

async function assertDuplicateDetailMatches(page: Page, target: DuplicateDocIdTarget): Promise<Record<string, unknown>> {
  await page.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => {});
  const url = page.url();
  const actualMasterId = new URL(url).searchParams.get("MasterID") ?? "";
  if (target.master_id && actualMasterId !== target.master_id) {
    throw new Error(`Detail page MasterID mismatch for ${target.doc_id}: ${url}`);
  }
  const rawBodyText = (await page.locator("body").textContent({ timeout: 5000 }).catch(() => "")) ?? "";
  const bodyText = normalizeText(rawBodyText);
  if (!target.master_id && !bodyText.includes(normalizeText(target.doc_id))) {
    throw new Error(`Detail page does not contain DocID ${target.doc_id}`);
  }
  if (target.emp_code && bodyText.includes(normalizeText("Employee")) && !bodyText.includes(normalizeText(target.emp_code))) {
    throw new Error(`Detail page does not contain employee ${target.emp_code} for ${target.doc_id}`);
  }
  return {
    current_url: url,
    actual_master_id: actualMasterId,
    body_snippet: rawBodyText.replace(/\s+/g, " ").trim().slice(0, 500),
    delete_button_visible: await page.locator("#MainContent_btnDelete").isVisible({ timeout: 1000 }).catch(() => false)
  };
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toUpperCase();
}

async function listPageSignature(page: Page): Promise<string> {
  const rows = await visibleDocumentRows(page);
  return rows.map((row) => `${row.masterId}:${row.docId}`).join("|");
}

export async function assertListPage(page: Page): Promise<void> {
  const url = page.url();
  if (/login|SessionExpire/i.test(url)) throw new Error(`Not authenticated on Plantware list page: ${url}`);
  await page.locator("#MainContent_gvLine, a[href*='frmPrTrxADDets.aspx?MasterID=']").first().waitFor({ state: "visible", timeout: 15000 });
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
