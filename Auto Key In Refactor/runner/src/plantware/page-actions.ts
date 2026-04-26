import type { Page } from "playwright";
import { PLANTWARE_CONFIG } from "../config.js";
import type { ManualAdjustmentRecord } from "../types.js";
import type { CategoryStrategy } from "../categories/registry.js";

export async function openDetailPage(page: Page): Promise<void> {
  await page.goto(`${PLANTWARE_CONFIG.baseUrl}${PLANTWARE_CONFIG.detailPage}`, {
    timeout: 30000,
    waitUntil: "networkidle"
  }).catch(async () => {
    await page.goto(`${PLANTWARE_CONFIG.baseUrl}${PLANTWARE_CONFIG.detailPage}`, {
      timeout: 45000,
      waitUntil: "domcontentloaded"
    });
  });
  await page.waitForTimeout(1500);
}

export async function rowAlreadyExists(page: Page, record: ManualAdjustmentRecord, category: CategoryStrategy): Promise<boolean> {
  const emp = normalizeText(record.emp_code);
  const adjustment = normalizeText(record.adjustment_name);
  const description = normalizeText(category.description(record));
  const adcode = normalizeText(category.adcode);
  const rowLike = page.locator("tr, [role='row'], .grid-row, .table-row, .rgRow, .rgAltRow");
  const rowCount = await rowLike.count().catch(() => 0);

  for (let index = 0; index < rowCount; index++) {
    const rowText = await rowLike.nth(index).textContent({ timeout: 1000 }).catch(() => "");
    const text = normalizeText(rowText ?? "");
    if (text.includes(emp) && [adjustment, description, adcode].some((token) => token && text.includes(token))) {
      return true;
    }
  }

  return false;
}

export async function fillAdjustmentRow(
  page: Page,
  record: ManualAdjustmentRecord,
  category: CategoryStrategy,
  isFirstRow: boolean
): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);

  if (!isFirstRow) {
    const newBtn = page.locator("#MainContent_btnNew, #btnNew, input[id*='btnNew']").first();
    if (await newBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newBtn.click();
      await page.waitForTimeout(2500);
    }
  }

  const empInput = page.locator("input.ui-autocomplete-input:not([disabled])").first();
  await selectAutocomplete(empInput, page, record.emp_code, 2000);

  if (isFirstRow) {
    const divisionSelect = page.locator("#MainContent_ddlChargeTo");
    if (await divisionSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      const currentValue = await divisionSelect.inputValue();
      if (currentValue !== PLANTWARE_CONFIG.division) await divisionSelect.selectOption(PLANTWARE_CONFIG.division);
    }
  }

  const adcodeInput = page.locator("input.ui-autocomplete-input:not([disabled])").nth(1);
  await selectAutocomplete(adcodeInput, page, category.adcode, 2500);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(3000);

  if (isFirstRow) {
    const descField = page.locator("#MainContent_txtDocDesc");
    if (await descField.isVisible({ timeout: 15000 }).catch(() => false)) {
      await descField.fill(category.description(record));
      await descField.press("Tab").catch(() => {});
    }
  }

  const amountField = page.locator("#MainContent_txtAmount");
  await amountField.waitFor({ state: "visible", timeout: 15000 });
  await amountField.clear();
  await amountField.fill(String(record.amount || 0));
  await amountField.press("Tab").catch(() => {});
  await page.waitForTimeout(1000);

  const expenseField = page.locator("input.CBOBox.ui-autocomplete-input:not([disabled])").last();
  if (await expenseField.isVisible({ timeout: 15000 }).catch(() => false)) {
    await selectAutocomplete(expenseField, page, "Labour", 2000);
  }

  const errorMsg = await page.locator("span[id*='RFV'], span:has-text('Please select'), span[style*='color: red']").textContent().catch(() => null);
  if (errorMsg) throw new Error(`Validation error: ${errorMsg}`);

  await page.waitForSelector("#MainContent_btnAdd", { timeout: 5000 });
  await page.click("#MainContent_btnAdd", { noWaitAfter: true });
}

export async function submitTab(page: Page): Promise<void> {
  const submitSelectors = ["#MainContent_btnSave", "#btnSave", "input[id*='btnSave']", "button[id*='Save']"];
  for (const selector of submitSelectors) {
    if (await page.locator(selector).first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await page.click(selector, { noWaitAfter: true });
      break;
    }
  }
  try {
    await page.waitForLoadState("networkidle", { timeout: 30000 });
  } catch {
    await page.waitForTimeout(3000);
  }
}

function normalizeText(value: string): string {
  return value.toUpperCase().replace(/\s+/g, " ").trim();
}

async function selectAutocomplete(locator: ReturnType<Page["locator"]>, page: Page, value: string, waitMs: number): Promise<void> {
  await locator.click();
  await locator.clear();
  await page.waitForTimeout(100);
  await locator.pressSequentially(value, { delay: 100 });
  await page.waitForTimeout(waitMs);
  const menuItems = page.locator(".ui-menu-item");
  await menuItems.first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  if (await menuItems.first().isVisible().catch(() => false)) {
    await menuItems.first().click();
  } else {
    await locator.press("ArrowDown");
    await page.waitForTimeout(200);
    await locator.press("Enter");
  }
  await page.waitForTimeout(500);
}
