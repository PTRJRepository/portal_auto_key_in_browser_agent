import type { Locator, Page } from "playwright";
import { PLANTWARE_CONFIG } from "../config.js";
import type { DuplicateDocIdTarget } from "../types.js";

export const TASK_REGISTER_LIST_PAGE = "/en/PR/trx/frmPrTrxTaskRegisterList.aspx";
const taskRegisterListUrl = `${PLANTWARE_CONFIG.baseUrl}${TASK_REGISTER_LIST_PAGE}`;

const SEARCH_INPUT_SELECTOR = "#MainContent_txtSrchDocID";
const SEARCH_CONTROL_SELECTORS = [
  "#MainContent_btnSearch",
  "#MainContent_btnSrch",
  "#MainContent_btnSearchDocID",
  "input[type='submit'][value='Search']",
  "input[type='button'][value='Search']",
  "button:has-text('Search')",
  "a:has-text('Search')"
];
const DELETE_LINK_SELECTOR = "#MainContent_gvList_lbDelete_0";
const LIST_READY_SELECTOR = "#MainContent_gvList, #MainContent_txtSrchDocID";

export interface TaskRegisterSearchMatch {
  docId: string;
  url: string;
  deleteVisible: boolean;
}

export async function gotoTaskRegisterListPage(page: Page): Promise<void> {
  await gotoPage(page, taskRegisterListUrl);
  await assertTaskRegisterListPage(page);
}

export async function assertTaskRegisterListPage(page: Page): Promise<void> {
  const url = page.url();
  if (/login|SessionExpire/i.test(url)) throw new Error(`Not authenticated on Plantware Task Register list page: ${url}`);
  await page.locator(LIST_READY_SELECTOR).first().waitFor({ state: "visible", timeout: 15000 });
}

export async function searchTaskRegisterDocId(page: Page, target: DuplicateDocIdTarget | string): Promise<TaskRegisterSearchMatch | null> {
  const docId = typeof target === "string" ? target : target.doc_id;
  if (!docId.trim()) throw new Error("Task Register DocID must not be empty");
  const searchInput = page.locator(SEARCH_INPUT_SELECTOR);
  await searchInput.fill(docId.trim());
  const searchControl = await firstVisibleLocator(page, SEARCH_CONTROL_SELECTORS);
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    searchControl ? searchControl.click({ noWaitAfter: true }) : searchInput.press("Enter")
  ]);
  await assertTaskRegisterListPage(page);
  return taskRegisterDocIdVisible(page, docId);
}

export async function deleteTaskRegisterDocId(page: Page, target: DuplicateDocIdTarget, debug: (event: Record<string, unknown>) => void = () => {}): Promise<void> {
  debug({ step: "task_register.search.before", doc_id: target.doc_id, target });
  const match = await searchTaskRegisterDocId(page, target);
  if (!match) {
    throw new Error(`Task Register DocID ${target.doc_id} not found`);
  }
  debug({ step: "task_register.search.matched", ...match, target });
  const deleteLink = page.locator(DELETE_LINK_SELECTOR).first();
  await deleteLink.waitFor({ state: "visible", timeout: 15000 });
  page.once("dialog", async (dialog) => {
    debug({ step: "task_register.delete.dialog", dialog_type: dialog.type(), dialog_message: dialog.message(), target });
    await dialog.accept();
  });
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    deleteLink.click({ noWaitAfter: true })
  ]);
  debug({ step: "task_register.delete.click.after", current_url: page.url(), target });
}

export async function taskRegisterDocIdVisible(page: Page, docId: string): Promise<TaskRegisterSearchMatch | null> {
  const normalizedTarget = normalizeDocId(docId);
  const grid = page.locator("#MainContent_gvList");
  const text = await grid.textContent({ timeout: 5000 }).catch(() => "");
  if (!normalizeDocId(text ?? "").includes(normalizedTarget)) return null;
  const deleteVisible = await page.locator(DELETE_LINK_SELECTOR).isVisible({ timeout: 1000 }).catch(() => false);
  return { docId: docId.trim(), url: page.url(), deleteVisible };
}

export function isTaskRegisterTarget(target: DuplicateDocIdTarget): boolean {
  const category = String(target.category ?? "").trim().toLowerCase();
  const source = String(target.raw?.source ?? "").trim().toLowerCase();
  return category === "task_register" || source === "task-register-pr-taskreg";
}

function normalizeDocId(value: string): string {
  return value.replace(/\s+/g, "").trim().toUpperCase();
}

async function firstVisibleLocator(page: Page, selectors: string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    const visible = await locator.isVisible({ timeout: 500 }).catch(() => false);
    if (visible) return locator;
  }
  return null;
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
