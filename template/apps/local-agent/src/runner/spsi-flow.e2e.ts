/**
 * SPSI Flow E2E Test
 *
 * High-fidelity end-to-end test for SPSI login and data entry flow.
 * Tests against plantwarep3:8001 with comprehensive step verification.
 */

import { chromium, type Browser, type Page } from "playwright";

const CONFIG = {
  baseUrl: "http://plantwarep3:8001",
  entryUrl: "http://plantwarep3:8001/",
  username: "adm075",
  password: "adm075",
  division: "AB1",
  divisionLabel: "ESTATE PARIT GUNUNG 1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx",
  timeout: {
    navigation: 20000,
    element: 15000,
    action: 10000
  }
};

interface StepResult {
  name: string;
  passed: boolean;
  duration: number;
  error?: string;
  screenshot?: string;
}

interface FlowResult {
  success: boolean;
  runId: string;
  startedAt: string;
  finishedAt: string;
  fidelityScore: number;
  steps: StepResult[];
}

async function captureScreenshot(page: Page, name: string): Promise<string> {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `e2e-${name}-${timestamp}.png`;
  await page.screenshot({ path: `./screenshots/${filename}`, fullPage: true });
  return filename;
}

async function waitForNetworkIdle(page: Page, timeoutMs: number = 10000): Promise<void> {
  try {
    await page.waitForLoadState("networkidle", { timeout: timeoutMs });
  } catch {
    await page.waitForLoadState("domcontentloaded");
  }
}

export async function runSpsiFlowE2E(): Promise<FlowResult> {
  const runId = `e2e-${Date.now()}`;
  const startedAt = new Date().toISOString();
  const steps: StepResult[] = [];
  let browser: Browser | undefined;
  let page: Page | undefined;

  const step = async (name: string, fn: () => Promise<void>) => {
    const start = Date.now();
    try {
      await fn();
      steps.push({ name, passed: true, duration: Date.now() - start });
    } catch (err) {
      const duration = Date.now() - start;
      const error = err instanceof Error ? err.message : String(err);
      steps.push({ name, passed: false, duration, error });
      if (page) {
        try {
          const screenshot = await captureScreenshot(page, name.replace(/\s+/g, "-").toLowerCase());
          steps[steps.length - 1].screenshot = screenshot;
        } catch {}
      }
      throw err;
    }
  };

  try {
    // Step 1: Launch browser
    await step("Launch browser", async () => {
      browser = await chromium.launch({
        headless: false,
        args: ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"]
      });
      const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
      page = await context.newPage();
    });

    // Step 2: Open login page
    await step("Open login page", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.goto(CONFIG.entryUrl, { timeout: CONFIG.timeout.navigation, waitUntil: "networkidle" });
    });

    // Step 3: Verify username input
    await step("Verify username input", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.waitForSelector("#txtUsername", { timeout: CONFIG.timeout.element });
    });

    // Step 4: Click username field
    await step("Click username field", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.click("#txtUsername", { timeout: CONFIG.timeout.action });
    });

    // Step 5: Type username
    await step("Type username", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.fill("#txtUsername", CONFIG.username, { timeout: CONFIG.timeout.action });
      const value = await page.locator("#txtUsername").inputValue();
      if (value !== CONFIG.username) throw new Error(`Username mismatch: "${value}"`);
    });

    // Step 6: Tab to password
    await step("Tab to password field", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.keyboard.press("Tab");
      await page.waitForTimeout(100);
    });

    // Step 7: Type password
    await step("Type password", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.fill("#txtPassword", CONFIG.password, { timeout: CONFIG.timeout.action });
    });

    // Step 8: Tab to submit
    await step("Tab to submit button", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.keyboard.press("Tab");
      await page.waitForTimeout(100);
    });

    // Step 9: Submit login
    await step("Submit login form", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.keyboard.press("Enter");
      await page.waitForURL(/frmSystemUserSetlocation\.aspx/, { timeout: CONFIG.timeout.navigation });
    });

    // Step 10: Verify location panel
    await step("Verify location panel", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.waitForSelector("#MainContent_pnlSetLocation > div", { timeout: CONFIG.timeout.element });
    });

    // Step 11: Select division
    await step(`Select division ${CONFIG.divisionLabel}`, async () => {
      if (!page) throw new Error("Page not initialized");
      const selector = `input[value="${CONFIG.division}"]`;
      await page.waitForSelector(selector, { timeout: CONFIG.timeout.element });
      await page.click(selector, { timeout: CONFIG.timeout.action });
      const isChecked = await page.locator(selector).isChecked();
      if (!isChecked) throw new Error(`Radio ${CONFIG.division} not checked`);
    });

    // Step 12: Click OK
    await step("Click OK button", async () => {
      if (!page) throw new Error("Page not initialized");
      // Wait for postback to complete after radio selection
      await page.waitForLoadState("networkidle", { timeout: CONFIG.timeout.element });
      // Try to wait for button visibility
      try {
        await page.waitForFunction(() => {
          const btn = document.getElementById("MainContent_btnOkay");
          return btn && (btn as HTMLElement).offsetParent !== null;
        }, { timeout: 5000 });
      } catch {
        // Button might be in a different state, try anyway
      }
      // Use evaluate to click via JS if not visible
      const isVisible = await page.locator("#MainContent_btnOkay").isVisible().catch(() => false);
      if (isVisible) {
        await page.click("#MainContent_btnOkay", { timeout: CONFIG.timeout.action });
      } else {
        // Execute click via JavaScript
        await page.evaluate(() => {
          const btn = document.getElementById("MainContent_btnOkay");
          if (btn) btn.click();
        });
      }
      await waitForNetworkIdle(page, CONFIG.timeout.navigation);
    });

    // Step 13: Navigate to PR Lists
    await step("Navigate to PR Lists", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.goto(`${CONFIG.baseUrl}${CONFIG.listPage}`, {
        timeout: CONFIG.timeout.navigation,
        waitUntil: "networkidle"
      });
    });

    // Step 14: Verify New button
    await step("Verify New button", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.waitForSelector("#MainContent_btnNew", { timeout: CONFIG.timeout.element });
    });

    // Step 15: Click New
    await step("Click New button", async () => {
      if (!page) throw new Error("Page not initialized");
      await page.click("#MainContent_btnNew", { timeout: CONFIG.timeout.action });
      await waitForNetworkIdle(page, CONFIG.timeout.element);
    });

    // Step 16: Verify autocomplete input (data entry point)
    await step("Verify autocomplete input (data entry point)", async () => {
      if (!page) throw new Error("Page not initialized");
      const selector = "input.ui-autocomplete-input";
      // Wait for at least one autocomplete input
      await page.waitForSelector(selector, { timeout: CONFIG.timeout.element });
      // Check if any exists (use first() to avoid strict mode)
      const count = await page.locator(selector).count();
      if (count === 0) throw new Error("No autocomplete inputs found");
    });

    // Step 17: Final verification
    await step("Final fidelity check", async () => {
      if (!page) throw new Error("Page not initialized");
      const url = page.url();
      const count = await page.locator("input.ui-autocomplete-input").count();
      // New button navigates to detail page (frmPrTrxADDets.aspx) - that's correct
      const isCorrectPage = url.includes("frmPrTrxAD") && url.includes("Lists") || url.includes("ADDets");
      if (!isCorrectPage) throw new Error(`Wrong final URL: ${url}`);
      if (count === 0) throw new Error("No autocomplete inputs at end - data entry point not reached");
    });

    const finishedAt = new Date().toISOString();
    const passedCount = steps.filter(s => s.passed).length;
    const fidelityScore = Math.round((passedCount / steps.length) * 100);

    return { success: true, runId, startedAt, finishedAt, fidelityScore, steps };

  } catch {
    const finishedAt = new Date().toISOString();
    const passedCount = steps.filter(s => s.passed).length;
    const fidelityScore = steps.length > 0 ? Math.round((passedCount / steps.length) * 100) : 0;
    return { success: false, runId, startedAt, finishedAt, fidelityScore, steps };
  } finally {
    if (browser) await browser.close();
  }
}

// CLI
async function main() {
  console.log("=".repeat(60));
  console.log("  SPSI Flow E2E Test - High Fidelity");
  console.log("=".repeat(60));
  console.log(`\nTarget: ${CONFIG.baseUrl}`);
  console.log(`User: ${CONFIG.username}`);
  console.log(`Division: ${CONFIG.divisionLabel}\n`);

  const result = await runSpsiFlowE2E();

  console.log("=".repeat(60));
  console.log("  RESULTS");
  console.log("=".repeat(60));
  console.log(`Status: ${result.success ? "✓ PASSED" : "✗ FAILED"}`);
  console.log(`Fidelity: ${result.fidelityScore}%`);
  console.log(`Run ID: ${result.runId}\n`);

  for (const step of result.steps) {
    const icon = step.passed ? "✓" : "✗";
    console.log(`${icon} [${step.duration}ms] ${step.name}`);
    if (step.error) console.log(`  └─ ${step.error}`);
    if (step.screenshot) console.log(`  └─ 📷 ${step.screenshot}`);
  }

  console.log("\n" + "-".repeat(60));
  process.exit(result.success ? 0 : 1);
}

main().catch(e => { console.error(e); process.exit(1); });