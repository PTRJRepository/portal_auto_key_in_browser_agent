/**
 * SPSI Multi-Tab Runner
 * Single browser instance with multiple tabs processing different PR data
 * Uses shared session for authentication
 */

import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const CONFIG = {
  baseUrl: "http://plantwarep3:8001",
  entryUrl: "http://plantwarep3:8001/",
  username: "adm075",
  password: "adm075",
  division: "P1B",
  divisionLabel: "ESTATE PARIT GUNUNG 1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx",
  detailPage: "/en/PR/trx/frmPrTrxADDets.aspx",
  sessionDir: path.resolve(process.cwd(), "../../../Runner/spsi_input/sessions"),
  sharedSessionId: "shared-session",
  maxTabs: 10
};

export interface PRData {
  id?: string | number;
  prNumber?: string;
  emp_code?: string;
  gang_code?: string;
  division_code?: string;
  adjustment_type?: string;
  adjustment_name?: string;
  adcode?: string;
  amount?: number;
  remarks?: string;
  [key: string]: unknown;
}

export interface TabResult {
  tabIndex: number;
  prNumber: string;
  success: boolean;
  duration: number;
  error?: string;
}

export interface MultiTabResult {
  success: boolean;
  totalTabs: number;
  successfulTabs: number;
  failedTabs: number;
  startedAt: string;
  finishedAt: string;
  results: TabResult[];
}

export class SpsiMultiTabRunner {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private headless: boolean = false;
  private sessionId: string;
  private sessionReused: boolean = false;

  constructor(
    private sessionName: string = CONFIG.sharedSessionId,
    private tabCount: number = 3,
    private headlessMode: boolean = false
  ) {
    this.headless = headlessMode;
    this.sessionId = sessionName;
  }

  async run(prDataList: PRData[]): Promise<MultiTabResult> {
    const startedAt = new Date().toISOString();
    const results: TabResult[] = [];

    if (!fs.existsSync(CONFIG.sessionDir)) {
      fs.mkdirSync(CONFIG.sessionDir, { recursive: true });
    }

    try {
      await this.launchBrowser();

      // Always do fresh login first, then use that session for multi-tab
      console.log("[MultiTab] Performing fresh login...");
      await this.loginAndSave();

      const actualTabCount = Math.min(
        this.tabCount,
        CONFIG.maxTabs,
        prDataList.length
      );

      console.log("[MultiTab] Starting " + actualTabCount + " tabs...");
      const pages: Page[] = [];
      for (let i = 0; i < actualTabCount; i++) {
        const page = await this.context!.newPage();
        pages.push(page);
      }

      console.log("[MultiTab] Navigating " + actualTabCount + " tabs to detail page...");
      await Promise.all(
        pages.map((page) =>
          page.goto(CONFIG.baseUrl + CONFIG.detailPage, {
            timeout: 30000,
            waitUntil: "networkidle"
          }).catch((err: Error) => {
            console.log("[MultiTab] Navigation error: " + err.message);
          })
        )
      );

      // Wait for all pages to settle
      await pages[0].waitForTimeout(2000);

      console.log("[MultiTab] Filling data in " + actualTabCount + " tabs...");
      const fillPromises = pages.map(async (page, tabIndex) => {
        const startTime = Date.now();
        let success = true;
        let errorMsg = "";

        // Get rows for this tab (distribute: tab 0 gets rows 0,3,6..., tab 1 gets rows 1,4,7...)
        const rowsForThisTab = prDataList.filter((_, idx) => idx % actualTabCount === tabIndex);
        console.log("[MultiTab] Tab " + tabIndex + " has " + rowsForThisTab.length + " rows");

        try {
          for (let rowIdx = 0; rowIdx < rowsForThisTab.length; rowIdx++) {
            const prData = rowsForThisTab[rowIdx];
            const isFirstRow = rowIdx === 0;

            console.log("[MultiTab] Tab " + tabIndex + " filling row " + rowIdx + ": emp=" + prData.emp_code);
            await this.fillTabData(page, prData, isFirstRow);
            await page.waitForTimeout(500);
          }
        } catch (err) {
          success = false;
          errorMsg = err instanceof Error ? err.message : "Unknown error";
          console.log("[MultiTab] Tab " + tabIndex + " error: " + errorMsg);
        }

        results.push({
          tabIndex: tabIndex,
          prNumber: "PR-" + tabIndex,
          success: success,
          duration: Date.now() - startTime,
          error: errorMsg
        });
      });

      await Promise.all(fillPromises);

      console.log("[MultiTab] Submitting " + actualTabCount + " tabs sequentially...");
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        const result = results[i];

        try {
          await this.submitTab(page);
          result.success = true;
        } catch (err) {
          result.success = false;
          result.error = err instanceof Error ? err.message : "Submit failed";
        }

        await page.waitForTimeout(500);
      }

      const finishedAt = new Date().toISOString();
      await Promise.all(pages.map((p) => p.close().catch(() => {})));

      const successfulTabs = results.filter((r) => r.success).length;

      return {
        success: successfulTabs === actualTabCount,
        totalTabs: actualTabCount,
        successfulTabs,
        failedTabs: actualTabCount - successfulTabs,
        startedAt,
        finishedAt,
        results
      };

    } catch (error) {
      const finishedAt = new Date().toISOString();
      return {
        success: false,
        totalTabs: prDataList.length,
        successfulTabs: results.filter((r) => r.success).length,
        failedTabs: results.filter((r) => !r.success).length,
        startedAt,
        finishedAt,
        results
      };
    } finally {
      await this.cleanup();
    }
  }

  private async launchBrowser(): Promise<void> {
    this.browser = await chromium.launch({
      headless: this.headless,
      args: [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-web-security"
      ]
    });

    this.context = await this.browser.newContext({
      viewport: { width: 1280, height: 720 }
    });
  }

  private async ensureAuthenticated(): Promise<boolean> {
    const sessionPath = path.join(CONFIG.sessionDir, this.sessionId + ".json");

    if (!fs.existsSync(sessionPath)) {
      console.log("[MultiTab] No session found, performing login...");
      return await this.loginAndSave();
    }

    try {
      const sessionData = JSON.parse(fs.readFileSync(sessionPath, "utf-8"));

      if (!sessionData.storageState?.cookies?.length) {
        return await this.loginAndSave();
      }

      const savedAt = new Date(sessionData.savedAt);
      const ageMinutes = (Date.now() - savedAt.getTime()) / 60000;
      if (ageMinutes > 240) {
        console.log("[MultiTab] Session too old, re-login...");
        return await this.loginAndSave();
      }

      const testContext = await this.browser!.newContext({
        storageState: sessionData.storageState
      });

      const testPage = await testContext.newPage();
      await testPage.goto(CONFIG.baseUrl + CONFIG.listPage, {
        timeout: 15000,
        waitUntil: "domcontentloaded"
      });

      const url = testPage.url();
      await testPage.close();
      await testContext.close();

      if (url.includes("login") || url.includes("SessionExpire")) {
        console.log("[MultiTab] Session invalid, re-login...");
        return await this.loginAndSave();
      }

      if (this.context) {
        await this.context.close().catch(() => {});
      }
      this.context = await this.browser!.newContext({
        storageState: sessionData.storageState,
        viewport: { width: 1280, height: 720 }
      });

      this.sessionReused = true;
      console.log("[MultiTab] Session reused successfully");
      return true;

    } catch (err) {
      console.log("[MultiTab] Session load failed: " + err);
      return await this.loginAndSave();
    }
  }

  private async loginAndSave(): Promise<boolean> {
    const page = await this.context!.newPage();

    try {
      await page.goto(CONFIG.entryUrl, { timeout: 30000, waitUntil: "networkidle" });
    } catch {
      await page.goto(CONFIG.entryUrl, { timeout: 45000, waitUntil: "domcontentloaded" });
    }

    await page.waitForSelector("#txtUsername", { timeout: 10000 });
    await page.fill("#txtUsername", CONFIG.username);
    await page.fill("#txtPassword", CONFIG.password);
    await page.click("#btnLogin");
    await page.waitForURL(/Setlocation/i, { timeout: 20000 });

    await page.waitForSelector("input[value='" + CONFIG.division + "']", { timeout: 5000 });
    await page.click("input[value='" + CONFIG.division + "']");

    await page.evaluate(() => {
      const btn = document.getElementById("MainContent_btnOkay");
      if (btn) (btn as HTMLButtonElement).click();
    });

    try {
      await page.waitForLoadState("networkidle", { timeout: 10000 });
    } catch {
      await page.waitForTimeout(3000);
    }

    await page.waitForURL(/frmPrTrxADLists/i, { timeout: 10000 }).catch(() => {});

    const sessionPath = path.join(CONFIG.sessionDir, this.sessionId + ".json");
    const storageState = await this.context!.storageState();

    fs.writeFileSync(sessionPath, JSON.stringify({
      sessionId: this.sessionId,
      savedAt: new Date().toISOString(),
      storageState
    }, null, 2));

    console.log("[MultiTab] Session saved to " + sessionPath);
    await page.close();

    return true;
  }

  private async fillTabData(page: Page, prData: PRData, isFirstRow: boolean = true): Promise<void> {
    // Wait for page to settle
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1500);

    // ===== For non-first rows, click New button to add row =====
    if (!isFirstRow) {
      const newBtn = page.locator("#MainContent_btnNew, #btnNew, input[id*='btnNew']").first();
      try {
        if (await newBtn.isVisible({ timeout: 3000 })) {
          await newBtn.click();
          await page.waitForTimeout(2500);
          console.log("[MultiTab] Clicked New button for next row");
        }
      } catch {}
    }

    // ===== Employee Code - clear first =====
    const empInput = page.locator("input.ui-autocomplete-input:not([disabled])").first();
    await empInput.click();
    await empInput.clear();
    await page.waitForTimeout(100);
    console.log("[MultiTab] Typing emp: " + prData.emp_code);
    await empInput.pressSequentially(prData.emp_code || "", { delay: 100 });
    await page.waitForTimeout(2000);

    let menuItems = page.locator(".ui-menu-item");
    await menuItems.first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    if (await menuItems.first().isVisible()) {
      await menuItems.first().click();
      console.log("[MultiTab] Selected emp from dropdown");
    } else {
      await empInput.press("ArrowDown");
      await page.waitForTimeout(200);
      await empInput.press("Enter");
      console.log("[MultiTab] Selected emp via ArrowDown+Enter");
    }
    await page.waitForTimeout(1000);

    // ===== Division - only for first row =====
    if (isFirstRow) {
      const divisionSelect = page.locator("#MainContent_ddlChargeTo");
      try {
        if (await divisionSelect.isVisible({ timeout: 3000 })) {
          const currentValue = await divisionSelect.inputValue();
          if (currentValue !== "P1B") {
            await divisionSelect.selectOption("P1B");
            console.log("[MultiTab] Set division to P1B");
          } else {
            console.log("[MultiTab] Division already P1B");
          }
        }
      } catch {}
    }

    // ===== Adcode (always needed for every row) =====
    let adcode = "spsi";
    if (prData.adjustment_name) {
      const name = prData.adjustment_name.toLowerCase();
      if (name.includes("spsi")) adcode = "spsi";
      else if (name.includes("jabatan")) adcode = "tunjangan jabatan";
      else if (name.includes("masa")) adcode = "masa kerja";
    }

    const adcodeInput = page.locator("input.ui-autocomplete-input:not([disabled])").nth(1);
    await adcodeInput.click();
    await adcodeInput.clear();
    await page.waitForTimeout(100);
    console.log("[MultiTab] Typing adcode: " + adcode);
    await adcodeInput.pressSequentially(adcode, { delay: 100 });
    await page.waitForTimeout(2500);

    menuItems = page.locator(".ui-menu-item");
    await menuItems.first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    if (await menuItems.first().isVisible()) {
      await menuItems.first().click();
      console.log("[MultiTab] Selected adcode from dropdown");
    } else {
      await adcodeInput.press("ArrowDown");
      await page.waitForTimeout(200);
      await adcodeInput.press("Enter");
      console.log("[MultiTab] Selected adcode via ArrowDown+Enter");
    }

    // ===== Wait for page refresh after adcode =====
    console.log("[MultiTab] Waiting for page refresh after adcode...");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);

    // ===== Description (txtDocDesc) - only for first row =====
    if (isFirstRow) {
      const descField = page.locator("#MainContent_txtDocDesc");
      try {
        await descField.waitFor({ state: "visible", timeout: 15000 });
        let description = prData.adjustment_name || "";
        if (description.toUpperCase().startsWith("AUTO ")) {
          description = description.substring(5);
        }
        console.log("[MultiTab] Filling description: " + description);
        await descField.fill(description);
        await descField.press("Tab").catch(() => {});
      } catch (err) {
        console.log("[MultiTab] Description field error: " + err);
      }
      await page.waitForTimeout(300);
    }

    // ===== Amount - clear first =====
    const amountField = page.locator("#MainContent_txtAmount");
    try {
      await amountField.waitFor({ state: "visible", timeout: 15000 });
      await amountField.clear();
      await page.waitForTimeout(100);

      const amountValue = prData.amount || 0;
      console.log("[MultiTab] Filling amount: " + amountValue);
      await amountField.fill(String(amountValue));
      await page.waitForTimeout(300);

      const afterFill = await amountField.inputValue();
      console.log("[MultiTab] Amount after fill: " + afterFill);

      await amountField.press("Tab").catch(() => {});
    } catch (err) {
      console.log("[MultiTab] Amount field error: " + err);
    }
    await page.waitForTimeout(1000);

    // ===== Expense - clear first =====
    const expenseField = page.locator("input.CBOBox.ui-autocomplete-input:not([disabled])").last();
    try {
      await expenseField.waitFor({ state: "visible", timeout: 15000 });
      await expenseField.click();
      await expenseField.clear();
      await page.waitForTimeout(100);
      await expenseField.pressSequentially("Labour", { delay: 150 });
      await page.waitForTimeout(2000);

      const dropdown = page.locator(".ui-menu-item").first();
      await dropdown.waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
      if (await dropdown.isVisible()) {
        await dropdown.click();
        console.log("[MultiTab] Selected expense from dropdown");
      } else {
        await expenseField.press("ArrowDown");
        await page.waitForTimeout(200);
        await expenseField.press("Enter");
        console.log("[MultiTab] Selected expense via ArrowDown+Enter");
      }
    } catch (err) {
      console.log("[MultiTab] Expense field error: " + err);
    }
    await page.waitForTimeout(500);

    // ===== Check for validation errors =====
    const errorMsg = await page.locator("span[id*='RFV'], span:has-text('Please select'), span[style*='color: red']").textContent().catch(() => null);
    if (errorMsg) {
      console.log("[MultiTab] Validation error detected: " + errorMsg + " - retrying...");
      // Retry the entire row
      await page.waitForTimeout(1000);
      return await this.fillTabData(page, prData, isFirstRow);
    }

    // ===== Click Add to save line item - no refresh wait =====
    try {
      await page.waitForSelector("#MainContent_btnAdd", { timeout: 5000 });
      await page.click("#MainContent_btnAdd", { noWaitAfter: true });
      console.log("[MultiTab] Row saved: emp=" + prData.emp_code);
    } catch (err) {
      console.log("[MultiTab] Add button error: " + err);
    }
  }

  private async submitTab(page: Page): Promise<void> {
    const submitSelectors = [
      "#MainContent_btnSave",
      "#btnSave",
      "input[id*='btnSave']",
      "button[id*='Save']"
    ];

    for (const selector of submitSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 3000 });
        await page.click(selector, { noWaitAfter: true });
        break;
      } catch {
        continue;
      }
    }

    try {
      await page.waitForLoadState("networkidle", { timeout: 30000 });
    } catch {
      await page.waitForTimeout(3000);
    }
  }

  private async cleanup(): Promise<void> {
    if (this.context) {
      await this.context.close().catch(() => {});
      this.context = null;
    }
    if (this.browser) {
      await this.browser.close().catch(() => {});
      this.browser = null;
    }
  }
}

async function main() {
  const args = process.argv.slice(2);

  const headless = !args.includes("--visible");
  const sessionId = args.find((a) => a.startsWith("--session="))?.split("=")[1] ?? CONFIG.sharedSessionId;
  const tabCount = parseInt(args.find((a) => a.startsWith("--tabs="))?.split("=")[1] ?? "3", 10);
  const dataFile = args.find((a) => a.startsWith("--data="))?.split("=")[1];

  const sampleData: PRData[] = [
    { id: "001", prNumber: "PR-2024-001", itemCode: "ITEM001", itemName: "Item Satu", quantity: 10 },
    { id: "002", prNumber: "PR-2024-002", itemCode: "ITEM002", itemName: "Item Dua", quantity: 20 },
    { id: "003", prNumber: "PR-2024-003", itemCode: "ITEM003", itemName: "Item Tiga", quantity: 30 },
    { id: "004", prNumber: "PR-2024-004", itemCode: "ITEM004", itemName: "Item Empat", quantity: 40 },
    { id: "005", prNumber: "PR-2024-005", itemCode: "ITEM005", itemName: "Item Lima", quantity: 50 },
  ];

  let prDataList: PRData[] = sampleData;
  if (dataFile && fs.existsSync(dataFile)) {
    const rawData = fs.readFileSync(dataFile, "utf-8");
    prDataList = JSON.parse(rawData);
  }

  console.log("=".repeat(60));
  console.log("  SPSI Multi-Tab Runner");
  console.log("=".repeat(60));
  console.log("Mode: " + (headless ? "HEADLESS" : "HEADFULL"));
  console.log("Session: " + sessionId);
  console.log("Tabs: " + tabCount);
  console.log("Data Items: " + prDataList.length);
  console.log("=".repeat(60));

  const runner = new SpsiMultiTabRunner(sessionId, tabCount, headless);
  const result = await runner.run(prDataList);

  console.log("");
  console.log("=".repeat(60));
  console.log("  RESULTS");
  console.log("=".repeat(60));
  console.log("Status: " + (result.success ? "SUCCESS" : "PARTIAL"));
  console.log("Tabs: " + result.successfulTabs + "/" + result.totalTabs + " successful");
  console.log("");

  for (const tab of result.results) {
    const icon = tab.success ? "[OK]" : "[FAIL]";
    console.log(icon + " Tab " + tab.tabIndex + " [" + tab.duration + "ms] " + tab.prNumber);
    if (tab.error) console.log("  -> " + tab.error);
  }

  const totalDuration = result.results.reduce((sum, r) => sum + r.duration, 0);
  console.log("");
  console.log("Total Duration: " + totalDuration + "ms");

  process.exit(result.success ? 0 : 1);
}

main().catch(console.error);

export { CONFIG as SPSI_CONFIG };