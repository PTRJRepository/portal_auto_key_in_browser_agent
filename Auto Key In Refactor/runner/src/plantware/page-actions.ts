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
  await assertDetailFormReady(page);
}

export async function assertDetailFormReady(page: Page): Promise<void> {
  const url = page.url();
  if (/login|SessionExpire/i.test(url)) throw new Error(`Plantware session is not on detail form: ${url}`);
  await page.waitForSelector("#MainContent_txtAmount", { timeout: 20000 });
  await page.waitForSelector("#MainContent_btnAdd", { timeout: 20000 });
  const autocompleteCount = await page.locator("input.ui-autocomplete-input:not([disabled])").count();
  if (autocompleteCount < 2) {
    throw new Error(`Plantware detail form is not ready: expected at least 2 autocomplete inputs, found ${autocompleteCount}`);
  }
}

export async function rowAlreadyExists(page: Page, record: ManualAdjustmentRecord, category: CategoryStrategy): Promise<boolean> {
  const employeeTokens = employeeMatchTokens(record);
  const adjustment = normalizeText(record.adjustment_name);
  const description = normalizeText(category.description(record));
  const adcode = normalizeText(category.adcode(record));
  const amountTokens = amountTextTokens(record.amount).map(normalizeText);
  const detailTokens = [
    record.subblok,
    record.subblok_raw,
    record.vehicle_code,
    record.vehicle_expense_code
  ].map((value) => normalizeText(value ?? ""));
  const rowLike = page.locator("tr, [role='row'], .grid-row, .table-row, .rgRow, .rgAltRow");
  const rowCount = await rowLike.count().catch(() => 0);

  for (let index = 0; index < rowCount; index++) {
    const rowText = await rowLike.nth(index).textContent({ timeout: 1000 }).catch(() => "");
    const text = normalizeText(rowText ?? "");
    const matchesAdjustment = [adjustment, description, adcode].some((token) => token && text.includes(token));
    const matchesAmount = amountTokens.some((token) => token && text.includes(token));
    const matchesDetail = detailTokens.some((token) => token && text.includes(token));
    const matchesEmployee = employeeTokens.some((token) => token && text.includes(token));
    if (record.adjustment_type === "PREMI") {
      const hasDetailToken = detailTokens.some(Boolean);
      if (matchesEmployee && matchesAdjustment && matchesAmount && (!hasDetailToken || matchesDetail)) {
        return true;
      }
      continue;
    }
    if (matchesEmployee && (matchesAdjustment || matchesAmount || matchesDetail)) {
      return true;
    }
  }

  return false;
}

export async function fillAdjustmentRow(
  page: Page,
  record: ManualAdjustmentRecord,
  category: CategoryStrategy,
  isFirstRow: boolean,
  division: string = PLANTWARE_CONFIG.division,
  options: { continueEmployeePremium?: boolean; continuePremiumDetails?: boolean } = {}
): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);
  const continuePremiumInput = shouldContinuePremiumInput(record, options);

  if (shouldOpenNewRow(record, isFirstRow, continuePremiumInput)) {
    const newBtn = page.locator("#MainContent_btnNew, #btnNew, input[id*='btnNew']").first();
    if (await newBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newBtn.click();
      await page.waitForTimeout(2500);
    }
  }

  const form = getDetailFormControls(page);

  let autocompleteCountBeforeAdCode = 0;
  if (shouldFillHeaderField("employee", continuePremiumInput)) {
    await selectAutocompleteField(page, employeeAutocompleteField(record), 2000);

    const divisionSelect = page.locator("#MainContent_ddlChargeTo");
    if (await divisionSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      const currentValue = await divisionSelect.inputValue();
      if (currentValue !== division) await divisionSelect.selectOption(division);
    }
  }

  if (shouldFillHeaderField("adcode", continuePremiumInput)) {
    autocompleteCountBeforeAdCode = await page.locator("input.ui-autocomplete-input:not([disabled])").count();
    await selectAutocompleteField(page, adcodeAutocompleteField(record, category), 2500);
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
  }

  const detailKind = premiumDetailKind(record);
  if (detailKind === "blok") {
    await fillBlockBasedMonthlyAllowanceDetails(page, record);
  } else if (detailKind === "kendaraan") {
    await fillVehicleBasedMonthlyAllowanceDetails(page, record);
  } else if (category.requiresGangAfterAdCode) {
    await selectGangAutocompleteAfterAdCode(page, record, autocompleteCountBeforeAdCode);
  }

  const descField = page.locator("#MainContent_txtDocDesc");
  if (await descField.isVisible({ timeout: 15000 }).catch(() => false)) {
    const description = category.description(record);
    const currentDescription = await descField.inputValue().catch(() => "");
    if (shouldFillAutocompleteValue(currentDescription, description)) {
      await descField.fill(description);
      await descField.press("Tab").catch(() => {});
    }
  }

  await form.amountField.waitFor({ state: "visible", timeout: 15000 });
  await form.amountField.clear();
  await form.amountField.fill(String(record.amount || 0));
  await form.amountField.press("Tab").catch(() => {});
  await page.waitForTimeout(1000);

  if (!detailKind) {
    const expenseField = page.locator("input.CBOBox.ui-autocomplete-input:not([disabled])").last();
    if (await expenseField.isVisible({ timeout: 15000 }).catch(() => false)) {
      await selectAutocomplete(expenseField, page, category.expenseCode(record), 2000);
    }
  }

  const errorMsg = await page.locator("span[id*='RFV'], span:has-text('Please select'), span[style*='color: red']").textContent().catch(() => null);
  if (errorMsg) throw new Error(`Validation error: ${errorMsg}`);

  await form.addButton.waitFor({ state: "visible", timeout: 5000 });
  await form.addButton.click({ noWaitAfter: true });
  await waitForAddCompleted(page, record, category);
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

function compactCode(value: string): string {
  return value.toUpperCase().replace(/\s+/g, "").trim();
}

export function shouldFillAutocompleteValue(currentValue: string, desiredValue: string): boolean {
  const current = normalizeText(currentValue);
  const desired = normalizeText(desiredValue);
  if (!current) return true;
  return !current.includes(desired) && !desired.includes(current);
}

export function shouldOpenNewRow(record: ManualAdjustmentRecord, isFirstRow: boolean, continuePremiumInput = false): boolean {
  if (isFirstRow) return false;
  return !continuePremiumInput;
}

export function shouldContinuePremiumInput(
  record: ManualAdjustmentRecord,
  options: { continueEmployeePremium?: boolean; continuePremiumDetails?: boolean } = {}
): boolean {
  return Boolean(record.adjustment_type === "PREMI" && options.continuePremiumDetails);
}

export function shouldFillHeaderField(field: "employee" | "adcode", continuePremiumInput: boolean): boolean {
  if (field === "employee") return !continuePremiumInput;
  return true;
}

export function employeeAutocompleteValue(record: ManualAdjustmentRecord): string {
  const empCode = (record.emp_code ?? "").trim();
  if (empCode && !isNikLikeIdentifier(empCode)) return empCode;

  const empName = (record.emp_name ?? "").trim();
  if (isUsableEmployeeName(empName)) return empName;

  throw new Error(`Employee autocomplete would use NIK for ${empCode || "blank emp_code"}; provide a valid emp_name or PTRJ EmpCode before auto key-in`);
}

function employeeMatchTokens(record: ManualAdjustmentRecord): string[] {
  return uniqueNonEmpty([
    employeeAutocompleteValue(record),
    !isNikLikeIdentifier(record.emp_code ?? "") ? record.emp_code : "",
    isUsableEmployeeName(record.emp_name ?? "") ? record.emp_name ?? "" : ""
  ].map(normalizeText));
}

function isNikLikeIdentifier(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (/[A-Za-z]/.test(trimmed)) return false;
  const digits = trimmed.replace(/\D/g, "");
  return digits.length >= 12;
}

function isUsableEmployeeName(value: string): boolean {
  const trimmed = value.trim();
  return /[A-Za-z]/.test(trimmed) && !isNikLikeIdentifier(trimmed);
}

function uniqueNonEmpty(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function amountTextTokens(amount: number): string[] {
  return [
    String(amount),
    amount.toLocaleString("en-US"),
    amount.toLocaleString("id-ID")
  ];
}

export type PremiumDetailKind = "blok" | "kendaraan" | "";

export function premiumDetailKind(record: ManualAdjustmentRecord): PremiumDetailKind {
  const detailType = (record.detail_type ?? "").trim().toLowerCase();
  if (["blok", "block", "subblok", "sub_block"].includes(detailType)) return "blok";
  if (["kendaraan", "vehicle", "veh"].includes(detailType)) return "kendaraan";
  if ((record.subblok ?? record.subblok_raw ?? "").trim()) return "blok";
  if ((record.vehicle_code ?? "").trim()) return "kendaraan";
  return "";
}

export function premiumDetailGroupKey(record: ManualAdjustmentRecord, category: CategoryStrategy): string {
  if (!premiumDetailKind(record)) return "";
  return [
    employeeAutocompleteValue(record),
    (record.estate || record.division_code || "").trim().toUpperCase(),
    normalizeText(record.adjustment_name),
    normalizeText(category.adcode(record))
  ].join("|");
}

export function shouldContinuePremiumDetails(
  previousRecord: ManualAdjustmentRecord | null,
  record: ManualAdjustmentRecord,
  previousCategory: CategoryStrategy | null,
  category: CategoryStrategy
): boolean {
  if (!previousRecord || !previousCategory) return false;
  const previousKey = premiumDetailGroupKey(previousRecord, previousCategory);
  const currentKey = premiumDetailGroupKey(record, category);
  return Boolean(previousKey && previousKey === currentKey);
}

export function blockDivisionAutocompleteValue(record: ManualAdjustmentRecord): string {
  const explicit = (record.divisioncode ?? "").trim().toUpperCase();
  if (explicit) return explicit;
  const gang = compactCode(record.gang_code ?? "");
  if (gang.length < 2) throw new Error(`Gang code is required for block-based PREMI row: ${record.emp_code}`);
  return `${gang[0]} ${gang[1]}`;
}

export function subBlockAutocompleteValue(record: ManualAdjustmentRecord): string {
  const raw = (record.subblok ?? record.subblok_raw ?? "").trim();
  const normalized = raw.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
  if (!normalized) throw new Error(`Sub block is required for block-based PREMI row: ${record.emp_code}`);

  const divisionSuffix = compactCode(blockDivisionAutocompleteValue(record));
  const withDivision = (code: string): string => {
    if (!divisionSuffix || code.endsWith(divisionSuffix)) return code;
    return `${code}${divisionSuffix}`;
  };

  if (/^[A-Z]{2}\d/.test(normalized)) return withDivision(normalized);
  if (/^P(?!M)/.test(normalized)) return withDivision(`PM${normalized.slice(1)}`);
  if (/^\d/.test(normalized)) return withDivision(`PM${normalized}`);
  return withDivision(normalized);
}

export function blockExpenseAutocompleteValue(record: ManualAdjustmentRecord): string {
  return (record.expense_code ?? "").trim().toUpperCase() || "L";
}

export function vehicleAutocompleteValue(record: ManualAdjustmentRecord): string {
  const value = (record.vehicle_code ?? "").trim().toUpperCase();
  if (!value) throw new Error(`Vehicle code is required for vehicle-based PREMI row: ${record.emp_code}`);
  return value;
}

export function vehicleExpenseAutocompleteValue(record: ManualAdjustmentRecord): string {
  const value = [record.vehicle_expense_code, record.expense_code]
    .map((candidate) => (candidate ?? "").trim().toUpperCase())
    .find(Boolean) ?? "";
  if (!value) throw new Error(`Vehicle expense code is required for vehicle-based PREMI row: ${record.emp_code}`);
  return value;
}

export interface AutocompleteFieldPlan {
  key: string;
  selectSelector: string;
  inputSelector: string;
  value: string;
}

export function shouldUseSingleRemainingAutocompleteFallback(field: AutocompleteFieldPlan): boolean {
  return field.key === "subblok" || field.key === "vehicle";
}

export function singleRemainingAutocompleteOptionIndex(optionTexts: string[]): number | null {
  const selectable = optionTexts
    .map((text, index) => ({ index, text: normalizeText(text) }))
    .filter((item) => Boolean(item.text));
  return selectable.length === 1 ? selectable[0].index : null;
}

// Plantware comboboxes are generated beside hidden selects; keep values mapped to their owning select.
export const detailFormControlSelectors = {
  empSelect: "#MainContent_ddlEmployee",
  empInput: "#MainContent_ddlEmployee + input.ui-autocomplete-input",
  adcodeSelect: "#MainContent_ddlTaskCode",
  adcodeInput: "#MainContent_ddlTaskCode + input.ui-autocomplete-input"
} as const;

export function employeeAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "employee",
    selectSelector: detailFormControlSelectors.empSelect,
    inputSelector: detailFormControlSelectors.empInput,
    value: employeeAutocompleteValue(record)
  };
}

export function adcodeAutocompleteField(record: ManualAdjustmentRecord, category: CategoryStrategy): AutocompleteFieldPlan {
  return {
    key: "adcode",
    selectSelector: detailFormControlSelectors.adcodeSelect,
    inputSelector: detailFormControlSelectors.adcodeInput,
    value: category.adcode(record)
  };
}

export function blockDivisionAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "block",
    selectSelector: "#MainContent_MultiDimAcc_ddlBlock",
    inputSelector: "#MainContent_MultiDimAcc_ddlBlock + input.ui-autocomplete-input",
    value: compactCode(blockDivisionAutocompleteValue(record))
  };
}

export function subBlockAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "subblok",
    selectSelector: "#MainContent_MultiDimAcc_ddlSubBlk",
    inputSelector: "#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input",
    value: subBlockAutocompleteValue(record)
  };
}

export function blockExpenseAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "expense",
    selectSelector: "#MainContent_MultiDimAcc_ddlExpCode",
    inputSelector: "#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input",
    value: blockExpenseAutocompleteValue(record)
  };
}

export function vehicleAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "vehicle",
    selectSelector: "#MainContent_MultiDimAcc_ddlVehCode",
    inputSelector: "#MainContent_MultiDimAcc_ddlVehCode + input.ui-autocomplete-input",
    value: vehicleAutocompleteValue(record)
  };
}

export function vehicleExpenseAutocompleteField(record: ManualAdjustmentRecord): AutocompleteFieldPlan {
  return {
    key: "vehicle_expense",
    selectSelector: "#MainContent_MultiDimAcc_ddlVehExpCode",
    inputSelector: "#MainContent_MultiDimAcc_ddlVehExpCode + input.ui-autocomplete-input",
    value: vehicleExpenseAutocompleteValue(record)
  };
}

function getDetailFormControls(page: Page) {
  return {
    empInput: page.locator(detailFormControlSelectors.empInput).first(),
    adcodeInput: page.locator(detailFormControlSelectors.adcodeInput).first(),
    amountField: page.locator("#MainContent_txtAmount"),
    addButton: page.locator("#MainContent_btnAdd")
  };
}

async function fillBlockBasedMonthlyAllowanceDetails(page: Page, record: ManualAdjustmentRecord): Promise<void> {
  await waitForMonthlyAllowanceSelector(page, "#MainContent_MultiDimAcc_ddlSubBlk, #MainContent_MultiDimAcc_trSubBlkCode", "block/sub block");
  await selectAutocompleteField(page, blockDivisionAutocompleteField(record), 2000);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);
  await selectAutocompleteField(page, subBlockAutocompleteField(record), 2000);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);
  await selectAutocompleteField(page, blockExpenseAutocompleteField(record), 1000);
}

async function fillVehicleBasedMonthlyAllowanceDetails(page: Page, record: ManualAdjustmentRecord): Promise<void> {
  await waitForMonthlyAllowanceSelector(page, "#MainContent_MultiDimAcc_ddlVehCode, #MainContent_MultiDimAcc_trVehCode", "vehicle");
  await selectAutocompleteField(page, vehicleAutocompleteField(record), 2000);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);
  await selectAutocompleteField(page, vehicleExpenseAutocompleteField(record), 1000);
}

function comboboxInputForSelect(page: Page, selectSelector: string) {
  return page.locator(`${selectSelector} + input.ui-autocomplete-input`).first();
}

async function waitForMonthlyAllowanceSelector(page: Page, selector: string, label: string): Promise<void> {
  await page.locator(selector).first().waitFor({ state: "attached", timeout: 15000 }).catch(async () => {
    const available = await page.locator("[id^='MainContent_MultiDimAcc_']").evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLElement).id).filter(Boolean).slice(0, 30)
    ).catch(() => []);
    throw new Error(`Monthly allowance ${label} controls not found after AD code; available controls: ${available.join(", ") || "-"}`);
  });
}

async function selectGangAutocompleteAfterAdCode(page: Page, record: ManualAdjustmentRecord, countBeforeAdCode: number): Promise<void> {
  const gangPrefix = record.gang_code.trim().slice(0, 2).toUpperCase();
  if (gangPrefix.length < 2) throw new Error(`Gang code is required for PREMI category: ${record.emp_code}`);

  const autocompleteInputs = page.locator("input.ui-autocomplete-input:not([disabled])");
  await page.waitForFunction(
    (previousCount) => document.querySelectorAll("input.ui-autocomplete-input:not([disabled])").length > previousCount,
    countBeforeAdCode,
    { timeout: 10000 }
  ).catch(() => {});

  const refreshedCount = await autocompleteInputs.count();
  const gangInput = refreshedCount > countBeforeAdCode ? autocompleteInputs.nth(countBeforeAdCode) : autocompleteInputs.nth(2);
  if (!(await gangInput.isVisible({ timeout: 5000 }).catch(() => false))) {
    throw new Error(`Gang autocomplete input not found after AD code for ${record.emp_code}; autocomplete count ${refreshedCount}`);
  }

  await selectAutocomplete(gangInput, page, gangPrefix, 2000);
}

async function waitForAddCompleted(page: Page, record: ManualAdjustmentRecord, category: CategoryStrategy): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(1000);
  const errorMsg = await page.locator("span[id*='RFV'], span:has-text('Please select'), span:has-text('required'), span[style*='color: red']").textContent().catch(() => null);
  if (errorMsg) throw new Error(`Validation error after Add: ${errorMsg}`);
  const amountValue = await page.locator("#MainContent_txtAmount").inputValue().catch(() => "");
  const amountNum = parseFloat(amountValue || "0");
  if (amountNum === 0 || !amountValue) return;
  if (amountNum !== record.amount) return;
  if (await rowAlreadyExists(page, record, category)) return;
  if (premiumDetailKind(record)) return;
  if (category.requiresGangAfterAdCode) return;
  throw new Error(`Add not confirmed for ${record.emp_code} / ${category.adcode(record)}`);
}

async function selectAutocomplete(locator: ReturnType<Page["locator"]>, page: Page, value: string, waitMs: number): Promise<void> {
  await locator.waitFor({ state: "visible", timeout: 15000 });
  const currentValue = await locator.inputValue().catch(() => "");
  if (!shouldFillAutocompleteValue(currentValue, value)) return;
  await locator.click();
  await locator.clear();
  await page.locator(".ui-menu-item").first().waitFor({ state: "hidden", timeout: 1000 }).catch(() => {});
  await locator.pressSequentially(value, { delay: 100 });
  await page.waitForTimeout(waitMs);
  const menuItems = page.locator(".ui-menu-item:visible");
  await menuItems.first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  if (await menuItems.first().isVisible().catch(() => false)) {
    await menuItems.first().click();
  } else {
    await locator.press("ArrowDown");
    await page.waitForTimeout(200);
    await locator.press("Enter");
  }
  await page.waitForTimeout(500);
  const selectedValue = await locator.inputValue().catch(() => "");
  if (!selectedValue.trim()) throw new Error(`Autocomplete selection failed for ${value}`);
}

async function selectAutocompleteField(page: Page, field: AutocompleteFieldPlan, waitMs: number): Promise<void> {
  const locator = page.locator(field.inputSelector).first();
  await locator.waitFor({ state: "visible", timeout: 15000 });
  const currentValue = await locator.inputValue().catch(() => "");
  if (!shouldFillAutocompleteValue(currentValue, field.value)) return;

  const selectedBySelect = await selectPairedHiddenSelect(page, field);
  if (selectedBySelect) {
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(waitMs);
    const selectedValue = await locator.inputValue().catch(() => "");
    if (!selectedValue.trim()) {
      throw new Error(`Autocomplete selection failed for ${field.key}: ${field.value}`);
    }
    return;
  }

  try {
    await typeAutocompleteAndChooseMatchingItem(locator, page, field);
  } catch (error) {
    if (!shouldUseSingleRemainingAutocompleteFallback(field)) throw error;
    await typeAutocompleteSlowlyAndChooseSingleRemainingItem(locator, page, field, error);
  }
  await page.waitForTimeout(500);
  const selectedValue = await locator.inputValue().catch(() => "");
  if (!selectedValue.trim()) {
    throw new Error(`Autocomplete selection failed for ${field.key}: ${field.value}`);
  }
}

async function selectPairedHiddenSelect(page: Page, field: AutocompleteFieldPlan): Promise<boolean> {
  return page.evaluate(({ selectSelector, inputSelector, value }) => {
    const normalize = (text: string) => text.toUpperCase().replace(/\s+/g, " ").trim();
    const wanted = normalize(value);
    const select = document.querySelector(selectSelector) as HTMLSelectElement | null;
    const input = document.querySelector(inputSelector) as HTMLInputElement | null;
    if (!select || !input) return false;
    const options = Array.from(select.options);
    const matched = options.find((option) => normalize(option.value) === wanted)
      ?? options.find((option) => normalize(option.textContent ?? "") === wanted)
      ?? options.find((option) => normalize(option.value).includes(wanted))
      ?? options.find((option) => normalize(option.textContent ?? "").includes(wanted))
      ?? options.find((option) => wanted.includes(normalize(option.textContent ?? "")) && normalize(option.textContent ?? "").length > 2);
    if (!matched || !matched.value) return false;
    select.value = matched.value;
    input.value = (matched.textContent ?? matched.value).trim();
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, field).catch(() => false);
}

async function typeAutocompleteAndChooseMatchingItem(
  locator: ReturnType<Page["locator"]>,
  page: Page,
  field: AutocompleteFieldPlan,
): Promise<void> {
  await locator.click();
  await locator.clear();
  await page.locator(".ui-menu-item:visible").first().waitFor({ state: "hidden", timeout: 1000 }).catch(() => {});
  await locator.pressSequentially(field.value, { delay: 100 });
  await page.waitForTimeout(1000);
  const menuItems = page.locator(".ui-menu-item:visible");
  await menuItems.first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  const count = await menuItems.count().catch(() => 0);
  const wanted = normalizeText(field.value);
  for (let index = 0; index < count; index++) {
    const item = menuItems.nth(index);
    const text = normalizeText(await item.textContent({ timeout: 500 }).catch(() => "") ?? "");
    if (text && (text.includes(wanted) || wanted.includes(text))) {
      await item.click();
      return;
    }
  }
  throw new Error(`No autocomplete option matched ${field.key}: ${field.value}`);
}

async function typeAutocompleteSlowlyAndChooseSingleRemainingItem(
  locator: ReturnType<Page["locator"]>,
  page: Page,
  field: AutocompleteFieldPlan,
  firstError: unknown,
): Promise<void> {
  await locator.click();
  await locator.clear();
  await page.locator(".ui-menu-item:visible").first().waitFor({ state: "hidden", timeout: 1000 }).catch(() => {});

  for (const character of field.value) {
    await locator.pressSequentially(character, { delay: 250 });
    await page.waitForTimeout(350);
    const optionIndex = await singleRemainingVisibleAutocompleteOptionIndex(page);
    if (optionIndex !== null) {
      await page.locator(".ui-menu-item:visible").nth(optionIndex).click();
      return;
    }
  }

  await page.waitForTimeout(1000);
  const optionIndex = await singleRemainingVisibleAutocompleteOptionIndex(page);
  if (optionIndex !== null) {
    await page.locator(".ui-menu-item:visible").nth(optionIndex).click();
    return;
  }

  const message = firstError instanceof Error ? firstError.message : String(firstError);
  throw new Error(`No unique autocomplete option remained for ${field.key}: ${field.value}; first attempt: ${message}`);
}

async function singleRemainingVisibleAutocompleteOptionIndex(page: Page): Promise<number | null> {
  const menuItems = page.locator(".ui-menu-item:visible");
  const count = await menuItems.count().catch(() => 0);
  if (!count) return null;
  const texts: string[] = [];
  for (let index = 0; index < count; index++) {
    texts.push(await menuItems.nth(index).textContent({ timeout: 300 }).catch(() => "") ?? "");
  }
  return singleRemainingAutocompleteOptionIndex(texts);
}
