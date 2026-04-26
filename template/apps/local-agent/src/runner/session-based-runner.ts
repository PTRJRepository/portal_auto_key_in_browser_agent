/**
 * SPSI Session-Based Runner
 * Reuses authenticated browser sessions for faster execution.
 * Stores session state in filesystem for persistence across runs.
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
  sessionDir: path.resolve(process.cwd(), "../../../Runner/spsi_input/sessions"),
  sharedSessionId: "shared-session"
};

export interface RunnerConfig {
  headless?: boolean;
  instanceId?: string;
  sessionId?: string;
  reuseSession?: boolean;
}

export interface StepResult {
  name: string;
  passed: boolean;
  duration: number;
  error?: string;
}

export interface FlowResult {
  success: boolean;
  runId: string;
  instanceId: string;
  sessionId: string;
  sessionReused: boolean;
  startedAt: string;
  finishedAt: string;
  headless: boolean;
  steps: StepResult[];
}

const duration = (start: number) => Date.now() - start;

export class SpsiSessionRunner {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private headless: boolean = false;
  private instanceId: string;
  private sessionId: string;
  private sessionReused: boolean = false;

  constructor(config: RunnerConfig = {}) {
    this.headless = config.headless ?? false;
    this.instanceId = config.instanceId ?? `instance-${Date.now()}`;
    this.sessionId = config.sessionId ?? `session-${Date.now()}`;
  }

  async run(): Promise<FlowResult> {
    const runId = `spsi-session-${Date.now()}`;
    const startedAt = new Date().toISOString();
    const steps: StepResult[] = [];

    // Ensure session directory exists
    if (!fs.existsSync(CONFIG.sessionDir)) {
      fs.mkdirSync(CONFIG.sessionDir, { recursive: true });
    }

    try {
      await this.launchBrowser();

      const sessionLoaded = await this.tryLoadSession();
      if (!sessionLoaded) {
        await this.login(steps);
        await this.selectLocation(steps);
        await this.saveSession();
      } else {
        this.sessionReused = true;
        steps.push({ name: "Reuse session", passed: true, duration: 0 });
      }

      await this.navigateToList(steps);
      await this.clickNewAndVerify(steps);

      const finishedAt = new Date().toISOString();
      return {
        success: true,
        runId,
        instanceId: this.instanceId,
        sessionId: this.sessionId,
        sessionReused: this.sessionReused,
        startedAt,
        finishedAt,
        headless: this.headless,
        steps
      };
    } catch (error) {
      const finishedAt = new Date().toISOString();
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      const failedStep = steps[steps.length - 1];
      if (failedStep && !failedStep.error) failedStep.error = errorMsg;
      return {
        success: false,
        runId,
        instanceId: this.instanceId,
        sessionId: this.sessionId,
        sessionReused: this.sessionReused,
        startedAt,
        finishedAt,
        headless: this.headless,
        steps
      };
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

  private getSessionPath(): string {
    return path.join(CONFIG.sessionDir, `${this.sessionId}.json`);
  }

  private async tryLoadSession(): Promise<boolean> {
    const sessionPath = this.getSessionPath();

    if (!fs.existsSync(sessionPath)) {
      return false;
    }

    try {
      const sessionData = JSON.parse(fs.readFileSync(sessionPath, "utf-8"));

      // Validate session structure
      if (!sessionData.storageState?.cookies?.length) {
        return false;
      }

      // Check session age - allow up to 4 hours
      const savedAt = new Date(sessionData.savedAt);
      const ageMinutes = (Date.now() - savedAt.getTime()) / 60000;
      if (ageMinutes > 240) {
        return false;
      }

      // Create a fresh context with the saved storage state (as object)
      const newContext = await this.browser!.newContext({
        storageState: sessionData.storageState,
        viewport: { width: 1280, height: 720 }
      });

      const testPage = await newContext.newPage();

      // Try accessing the list page
      await testPage.goto(`${CONFIG.baseUrl}${CONFIG.listPage}`, {
        timeout: 15000,
        waitUntil: "domcontentloaded"
      });

      const url = testPage.url();

      // Check if we're on the login page - session needs re-login
      if (url.includes("login") || url.includes("Login") || url.includes("SessionExpire")) {
        await testPage.close();
        if (this.context) {
          await this.context.close().catch(() => {});
        }
        this.context = newContext;
        this.page = await newContext.newPage();
        return false; // Trigger standard login flow
      }

      // Check for expected UI elements
      let sessionValid = false;
      try {
        await testPage.waitForSelector("#MainContent_btnNew", { timeout: 5000 });
        sessionValid = true;
      } catch {
        // Check if page has any content indicating we're logged in
        const bodyText = await testPage.textContent("body").catch(() => null) ?? "";
        if (bodyText.includes("PR") || bodyText.includes("Purchase")) {
          sessionValid = true;
        }
      }

      if (!sessionValid) {
        await testPage.close();
        await newContext.close();
        return false;
      }

      // Valid session - use it
      if (this.context) {
        await this.context.close().catch(() => {});
      }
      this.context = newContext;
      this.page = await newContext.newPage(); // Fresh page on validated context

      return true;
    } catch {
      return false;
    }
  }

  private async saveSession(): Promise<void> {
    const sessionPath = this.getSessionPath();
    const storageState = await this.context!.storageState();

    fs.writeFileSync(sessionPath, JSON.stringify({
      sessionId: this.sessionId,
      savedAt: new Date().toISOString(),
      storageState
    }, null, 2));
  }

  private async login(steps: StepResult[]): Promise<void> {
    await this.execute("Login", async () => {
      try {
        await this.page!.goto(CONFIG.entryUrl, { timeout: 30000, waitUntil: "networkidle" });
      } catch {
        await this.page!.goto(CONFIG.entryUrl, { timeout: 45000, waitUntil: "domcontentloaded" });
      }
      await this.page!.waitForSelector("#txtUsername", { timeout: 10000 });

      await this.page!.fill("#txtUsername", CONFIG.username);
      await this.page!.fill("#txtPassword", CONFIG.password);
      await this.page!.click("#btnLogin");
      await this.page!.waitForURL(/frmSystemUserSetlocation\.aspx/i, { timeout: 20000 });
    }, steps);
  }

  private async selectLocation(steps: StepResult[]): Promise<void> {
    // Wait for location panel first
    await this.execute("Wait for location panel", async () => {
      await this.page!.waitForSelector("#MainContent_pnlSetLocation > div", { timeout: 5000 });
    }, steps);

    // Select division
    await this.execute("Select division", async () => {
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 5000 });
      } catch {}

      const selector = `input[value="${CONFIG.division}"]`;
      await this.page!.waitForSelector(selector, { timeout: 5000 });
      await this.page!.click(selector, { timeout: 10000, noWaitAfter: true });
      const isChecked = await this.page!.locator(selector).isChecked();
      if (!isChecked) throw new Error(`Radio ${CONFIG.division} not checked`);
    }, steps);

    // Confirm location
    await this.execute("Confirm location", async () => {
      // Wait for postback
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 60000 });
      } catch {
        await this.page!.waitForTimeout(5000);
      }

      // Click OK using evaluate (bypasses visibility check)
      // Catch "context destroyed" - it's normal for ASP.NET postback
      try {
        await this.page!.evaluate(() => {
          const btn = document.getElementById("MainContent_btnOkay");
          if (btn) (btn as HTMLButtonElement).click();
        });
      } catch (err: unknown) {
        if (typeof err === 'object' && err !== null && 'message' in err && (err as {message?: string}).message?.includes("Execution context was destroyed")) {
          // Ignore - this is normal for ASP.NET postback
        } else {
          throw err;
        }
      }

      // Wait for navigation
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 120000 });
      } catch {
        await this.page!.waitForTimeout(5000);
      }

      // Navigate to list page
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

      try {
        await this.page!.goto(url, { timeout: 30000, waitUntil: "networkidle" });
        await this.page!.waitForSelector("#MainContent_btnNew", { timeout: 10000 });
      } catch {
        await this.page!.goto(url, { timeout: 30000, waitUntil: "domcontentloaded" });
      }
    }, steps);
  }

  private async clickNewAndVerify(steps: StepResult[]): Promise<void> {
    await this.execute("Click New", async () => {
      try {
        await this.page!.waitForLoadState("networkidle", { timeout: 10000 });
      } catch {}
      await this.page!.waitForSelector("#MainContent_btnNew", { timeout: 10000 });

      await this.page!.evaluate(() => {
        const btn = document.getElementById("MainContent_btnNew");
        if (btn) btn.click();
      });

      try {
        await this.page!.waitForURL(/frmPrTrxADDets\.aspx/i, { timeout: 15000 });
      } catch {
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
  const instanceId = args.find(a => a.startsWith("--id="))?.split("=")[1] ?? `spsi-session-${Date.now()}`;
  const sessionId = args.find(a => a.startsWith("--session="))?.split("=")[1] ?? CONFIG.sharedSessionId;
  const reuseSession = !args.includes("--no-reuse");

  console.log("=".repeat(60));
  console.log("  SPSI Session-Based Runner");
  console.log("=".repeat(60));
  console.log(`Mode: ${headless ? "HEADLESS" : "HEADFULL"}`);
  console.log(`Instance: ${instanceId}`);
  console.log(`Session: ${sessionId}`);
  console.log(`Reuse Session: ${reuseSession}\n`);

  const runner = new SpsiSessionRunner({ headless, instanceId, sessionId, reuseSession });
  const result = await runner.run();

  console.log("=".repeat(60));
  console.log("  RESULTS");
  console.log("=".repeat(60));
  console.log(`Status: ${result.success ? "✓ SUCCESS" : "✗ FAILED"}`);
  console.log(`Session Reused: ${result.sessionReused ? "Yes" : "No"}`);
  console.log(`Session ID: ${result.sessionId}\n`);

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
