/**
 * SPSI Flow Runner - Production Optimized
 * Fastest possible with robust error recovery
 */

import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

const CONFIG = {
  baseUrl: "http://plantwarep3:8001",
  entryUrl: "http://plantwarep3:8001/",
  username: "adm075",
  password: "adm075",
  division: "P1B",
  divisionLabel: "ESTATE PARIT GUNUNG 1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx"
};

export interface RunnerConfig { headless?: boolean; instanceId?: string; }
export interface StepResult { name: string; passed: boolean; duration: number; error?: string; }
export interface FlowResult {
  success: boolean; runId: string; instanceId: string; startedAt: string; finishedAt: string;
  headless: boolean; steps: StepResult[];
}

const duration = (start: number) => Date.now() - start;

export class SpsiFlowRunner {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private headless: boolean = false;
  private instanceId: string;

  constructor(config: RunnerConfig = {}) {
    this.headless = config.headless ?? false;
    this.instanceId = config.instanceId ?? `instance-${Date.now()}`;
  }

  async run(): Promise<FlowResult> {
    const runId = `spsi-${Date.now()}`;
    const startedAt = new Date().toISOString();
    const steps: StepResult[] = [];

    try {
      await this.launchBrowser();
      await this.login(steps);
      await this.selectLocation(steps);
      await this.navigateToList(steps);
      await this.clickNewAndVerify(steps);
      const finishedAt = new Date().toISOString();
      return { success: true, runId, instanceId: this.instanceId, startedAt, finishedAt, headless: this.headless, steps };
    } catch (error) {
      const finishedAt = new Date().toISOString();
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      const failedStep = steps[steps.length - 1];
      if (failedStep && !failedStep.error) failedStep.error = errorMsg;
      return { success: false, runId, instanceId: this.instanceId, startedAt, finishedAt, headless: this.headless, steps };
    } finally {
      await this.cleanup();
    }
  }

  private async launchBrowser(): Promise<void> {
    this.browser = await chromium.launch({
      headless: this.headless,
      args: ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"]
    });
    this.context = await this.browser.newContext({ viewport: { width: 1280, height: 720 } });
    this.page = await this.context.newPage();
  }

  private async execute(name: string, fn: () => Promise<void>, steps: StepResult[]): Promise<void> {
    const start = Date.now();
    try {
      await fn();
      steps.push({ name, passed: true, duration: duration(start) });
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Unknown error";
      steps.push({ name, passed: false, duration: duration(start), error: msg });
      throw error;
    }
  }

  private async login(steps: StepResult[]): Promise<void> {
    await this.execute("Open login page", async () => {
      try {
        await this.page!.goto(CONFIG.entryUrl, { timeout: 30000, waitUntil: "networkidle" });
      } catch {
        await this.page!.goto(CONFIG.entryUrl, { timeout: 45000, waitUntil: "domcontentloaded" });
      }
      await this.page!.waitForSelector("#txtUsername", { timeout: 10000 });
    }, steps);

    await this.execute("Login", async () => {
      await this.page!.fill("#txtUsername", CONFIG.username);
      await this.page!.fill("#txtPassword", CONFIG.password);
      await this.page!.click("#btnLogin");
      await this.page!.waitForURL(/frmSystemUserSetlocation\.aspx/i, { timeout: 20000 });
    }, steps);
  }

  private async selectLocation(steps: StepResult[]): Promise<void> {
    await this.execute("Wait for location panel", async () => {
      await this.page!.waitForSelector("#MainContent_pnlSetLocation > div", { timeout: 5000 });
    }, steps);

    await this.execute("Select division", async () => {
      // Wait for network to settle before interacting
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 5000 });
      } catch {}

      const selector = `input[value="${CONFIG.division}"]`;
      await this.page!.waitForSelector(selector, { timeout: 5000 });
      // Use noWaitAfter since radio click triggers ASP.NET postback without navigation
      await this.page!.click(selector, { timeout: 10000, noWaitAfter: true });
      const isChecked = await this.page!.locator(selector).isChecked();
      if (!isChecked) throw new Error(`Radio ${CONFIG.division} not checked`);
    }, steps);

    await this.execute("Confirm location", async () => {
      // Wait for any pending network activity to settle
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 10000 });
      } catch {}

      // Wait for button to be visible
      try {
        await this.page!.waitForFunction(() => {
          const btn = document.getElementById("MainContent_btnOkay");
          return btn && (btn as HTMLElement).offsetParent !== null;
        }, { timeout: 5000 });
      } catch {}

      // Check visibility and click accordingly
      const isVisible = await this.page!.locator("#MainContent_btnOkay").isVisible().catch(() => false);

      if (isVisible) {
        await this.page!.click("#MainContent_btnOkay", { timeout: 10000 });
      } else {
        await this.page!.evaluate(() => {
          const btn = document.getElementById("MainContent_btnOkay");
          if (btn) (btn as HTMLButtonElement).click();
        });
      }

      // Wait for postback to complete
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 120000 });
      } catch {
        await this.page!.waitForTimeout(5000);
      }

      // Proceed to next page regardless - the server may have set location even if URL shows Setlocation
      // Navigate directly to the list page
      await this.page!.goto(`${CONFIG.baseUrl}${CONFIG.listPage}`, {
        timeout: 30000,
        waitUntil: "domcontentloaded"
      }).catch(() => {});
    }, steps);
  }

  private async navigateToList(steps: StepResult[]): Promise<void> {
    await this.execute("Navigate to PR Lists", async () => {
      const url = `${CONFIG.baseUrl}${CONFIG.listPage}`;
      const currentUrl = this.page!.url();
      if (currentUrl.includes("frmPrTrxADLists")) return;

      // Retry with backoff
      for (let attempt = 1; attempt <= 5; attempt++) {
        try {
          await this.page!.goto(url, { timeout: 30000, waitUntil: "networkidle" });
          await this.page!.waitForSelector("#MainContent_btnNew", { timeout: 10000 });
          return;
        } catch {
          if (attempt < 5) {
            await this.page!.waitForTimeout(2000 * attempt);
            try {
              await this.page!.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
              await this.page!.waitForSelector("#MainContent_btnNew", { timeout: 10000 });
              return;
            } catch {}
          }
        }
      }
      // Final attempt
      try {
        await this.page!.goto(url, { timeout: 30000, waitUntil: "domcontentloaded" });
      } catch {}
    }, steps);
  }

  private async clickNewAndVerify(steps: StepResult[]): Promise<void> {
    await this.execute("Click New", async () => {
      // Wait for list page to be fully loaded
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 10000 });
      } catch {}
      await this.page!.waitForSelector("#MainContent_btnNew", { timeout: 10000 });

      // Click New button - use noWaitAfter since it triggers navigation
      await this.page!.evaluate(() => {
        const btn = document.getElementById("MainContent_btnNew");
        if (btn) btn.click();
      });

      // Wait for navigation to detail page
      try {
        await this.page!.waitForURL(/frmPrTrxADDets\.aspx/i, { timeout: 15000 });
      } catch {
        // Fallback - wait for autocomplete input to appear
        await this.page!.waitForTimeout(3000);
      }
    }, steps);

    await this.execute("Verify data entry", async () => {
      await this.page!.waitForSelector("input.ui-autocomplete-input", { timeout: 15000 });
    }, steps);
  }

  private async cleanup(): Promise<void> {
    if (this.page) { await this.page.close().catch(() => {}); this.page = null; }
    if (this.context) { await this.context.close().catch(() => {}); this.context = null; }
    if (this.browser) { await this.browser.close().catch(() => {}); this.browser = null; }
  }
}

async function main() {
  const args = process.argv.slice(2);
  const headless = args.includes("--headless");
  const instanceId = args.find(a => a.startsWith("--id="))?.split("=")[1] ?? `spsi-${Date.now()}`;

  console.log("=".repeat(60));
  console.log("  SPSI Flow Runner - Production");
  console.log("=".repeat(60));
  console.log(`Mode: ${headless ? "HEADLESS" : "HEADFULL"}`);
  console.log(`Instance: ${instanceId}\n`);

  const runner = new SpsiFlowRunner({ headless, instanceId });
  const result = await runner.run();

  console.log("=".repeat(60));
  console.log("  RESULTS");
  console.log("=".repeat(60));
  console.log(`Status: ${result.success ? "✓ SUCCESS" : "✗ FAILED"}\n`);

  for (const step of result.steps) {
    const icon = step.passed ? "✓" : "✗";
    console.log(`${icon} [${step.duration}ms] ${step.name}`);
    if (step.error) console.log(`  └─ ${step.error}`);
  }

  const totalDuration = result.steps.reduce((sum, s) => sum + s.duration, 0);
  console.log(`\nTotal Duration: ${totalDuration}ms`);
  process.exit(result.success ? 0 : 1);
}

main().catch(console.error);

export { CONFIG as SPSI_CONFIG };