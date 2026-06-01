#!/usr/bin/env tsx
import * as fs from "node:fs";
import type { Page } from "playwright";
import { resolveCategory } from "../categories/registry.js";
import { BrowserSession } from "../session/browser-session.js";
import type { ManualAdjustmentRecord, RunPayload } from "../types.js";
import { openDetailPage } from "./page-actions.js";

type LayoutControl = {
  tag: string;
  id: string;
  name: string;
  label: string;
  value: string;
  text: string;
  inputType: string;
  visible: boolean;
};

function argValue(name: string, fallback = ""): string {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  if (match) return match.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

async function selectHiddenCombobox(page: Page, selectSelector: string, inputSelector: string, wantedValue: string): Promise<string> {
  await page.locator(selectSelector).waitFor({ state: "attached", timeout: 15000 });
  await page.locator(inputSelector).waitFor({ state: "attached", timeout: 15000 });
  let selectedText = "";
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      selectedText = await page.evaluate(({ selectSelector, inputSelector, wantedValue }) => {
        const normalize = (value: string) => value.toUpperCase().replace(/\s+/g, " ").trim();
        const wanted = normalize(wantedValue);
        const select = document.querySelector(selectSelector) as HTMLSelectElement | null;
        const input = document.querySelector(inputSelector) as HTMLInputElement | null;
        if (!select || !input) throw new Error(`Combobox not found: ${selectSelector}`);
        const options = Array.from(select.options);
        const matched = options.find((option) => normalize(option.value) === wanted)
          ?? options.find((option) => normalize(option.textContent ?? "") === wanted)
          ?? options.find((option) => normalize(option.value).includes(wanted))
          ?? options.find((option) => normalize(option.textContent ?? "").includes(wanted));
        if (!matched || !matched.value) throw new Error(`Option not found for ${wantedValue} in ${selectSelector}`);
        select.value = matched.value;
        input.value = (matched.textContent ?? matched.value).trim();
        return input.value;
      }, { selectSelector, inputSelector, wantedValue });
      break;
    } catch (error) {
      if (attempt === 2) throw error;
      await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(1000);
    }
  }
  await page.evaluate(({ selectSelector, inputSelector }) => {
    const select = document.querySelector(selectSelector) as HTMLSelectElement | null;
    const input = document.querySelector(inputSelector) as HTMLInputElement | null;
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    select?.dispatchEvent(new Event("change", { bubbles: true }));
  }, { selectSelector, inputSelector }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(2500);
  return selectedText;
}

async function snapshotControlsBelowAdCode(page: Page): Promise<LayoutControl[]> {
  return page.locator("#aspnetForm, body").first().evaluate((form) => {
    const isVisible = (element: Element): boolean => {
      const html = element as HTMLElement;
      const style = window.getComputedStyle(html);
      return style.display !== "none" && style.visibility !== "hidden" && html.offsetParent !== null;
    };
    const labelFor = (element: Element): string => {
      const row = element.closest("tr");
      if (!row) return "";
      const cells = Array.from(row.querySelectorAll("td"));
      return (cells[0]?.textContent ?? "").replace(/\s+/g, " ").trim();
    };
    const adCode = form.querySelector("#MainContent_ddlTaskCode");
    const controls = Array.from(form.querySelectorAll("select, input, textarea"));
    const startIndex = adCode ? controls.indexOf(adCode as HTMLSelectElement) : -1;
    return controls.slice(Math.max(0, startIndex + 1)).map((element) => {
      const input = element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
      return {
        tag: element.tagName.toLowerCase(),
        id: input.id || "",
        name: input.name || "",
        label: labelFor(element),
        value: input.value || "",
        text: element.tagName.toLowerCase() === "select"
          ? (((input as HTMLSelectElement).selectedOptions[0]?.textContent ?? "").replace(/\s+/g, " ").trim())
          : "",
        inputType: (input as HTMLInputElement).type || "",
        visible: isVisible(element)
      };
    }).filter((control) => control.id || control.name || control.label);
  });
}

async function main(): Promise<void> {
  const payloadPath = argValue("payload");
  if (!payloadPath) throw new Error("Missing --payload <path>");
  const rowIndex = Number(argValue("row-index", "0"));
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf-8")) as RunPayload;
  const record = payload.records[rowIndex] as ManualAdjustmentRecord | undefined;
  if (!record) throw new Error(`Row index ${rowIndex} not found in payload`);
  const category = resolveCategory(record, payload.category_key);
  const session = new BrowserSession({ headless: payload.headless, freshLoginFirst: false, division: payload.division_code });
  process.stdout.write(JSON.stringify({ event: "debug.step", step: "session.start", division_code: payload.division_code }) + "\n");
  await session.start();
  const page = await session.newPage();
  try {
    process.stdout.write(JSON.stringify({ event: "debug.step", step: "openDetailPage" }) + "\n");
    await openDetailPage(page);
    process.stdout.write(JSON.stringify({ event: "debug.step", step: "select.employee", emp_code: record.emp_code }) + "\n");
    const employee = await selectHiddenCombobox(page, "#MainContent_ddlEmployee", "#MainContent_ddlEmployee + input.ui-autocomplete-input", record.emp_code);
    const chargeTo = page.locator("#MainContent_ddlChargeTo");
    if (await chargeTo.isVisible({ timeout: 3000 }).catch(() => false)) {
      process.stdout.write(JSON.stringify({ event: "debug.step", step: "select.charge_to", division_code: payload.division_code }) + "\n");
      await chargeTo.selectOption(payload.division_code).catch(() => {});
      await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(1000);
    }
    process.stdout.write(JSON.stringify({ event: "debug.step", step: "select.adcode", adcode: category.adcode(record) }) + "\n");
    const adcode = await selectHiddenCombobox(page, "#MainContent_ddlTaskCode", "#MainContent_ddlTaskCode + input.ui-autocomplete-input", category.adcode(record));
    process.stdout.write(JSON.stringify({ event: "debug.step", step: "snapshot" }) + "\n");
    const controls = await snapshotControlsBelowAdCode(page);
    process.stdout.write(JSON.stringify({
      event: "debug.adcode_layout",
      emp_code: record.emp_code,
      adjustment_name: record.adjustment_name,
      category_key: category.key,
      employee,
      adcode,
      metadata: {
        detail_type: record.detail_type ?? "",
        divisioncode: record.divisioncode ?? "",
        subblok: record.subblok ?? "",
        subblok_raw: record.subblok_raw ?? "",
        vehicle_code: record.vehicle_code ?? "",
        expense_code: record.expense_code ?? "",
        vehicle_expense_code: record.vehicle_expense_code ?? ""
      },
      controls
    }, null, 2) + "\n");
  } finally {
    await page.close().catch(() => {});
    await session.close();
  }
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({
    event: "debug.failed",
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack ?? "" : ""
  }, null, 2) + "\n");
  process.exit(1);
});
