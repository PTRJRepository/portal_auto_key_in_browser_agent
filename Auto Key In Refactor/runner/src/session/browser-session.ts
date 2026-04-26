import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";
import { PLANTWARE_CONFIG } from "../config.js";

export interface BrowserSessionOptions {
  headless: boolean;
  sessionId?: string;
  sessionDir?: string;
  freshLoginFirst?: boolean;
}

export class BrowserSession {
  browser: Browser | null = null;
  context: BrowserContext | null = null;
  sessionReused = false;
  private sessionId: string;
  private sessionDir: string;
  private freshLoginFirst: boolean;
  private headless: boolean;

  constructor(options: BrowserSessionOptions) {
    this.headless = options.headless;
    this.sessionId = options.sessionId ?? PLANTWARE_CONFIG.sharedSessionId;
    this.sessionDir = options.sessionDir ?? path.resolve(process.cwd(), "data/sessions");
    this.freshLoginFirst = options.freshLoginFirst ?? true;
  }

  async start(): Promise<void> {
    fs.mkdirSync(this.sessionDir, { recursive: true });
    this.browser = await chromium.launch({
      headless: this.headless,
      args: [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-web-security"
      ]
    });
    this.context = await this.browser.newContext({ viewport: { width: 1280, height: 720 } });
    if (this.freshLoginFirst) {
      await this.loginAndSave();
      return;
    }
    const loaded = await this.tryLoadSession();
    if (!loaded) await this.loginAndSave();
  }

  async newPage(): Promise<Page> {
    if (!this.context) throw new Error("Browser context is not started");
    return await this.context.newPage();
  }

  async loginAndSave(): Promise<void> {
    if (!this.context) throw new Error("Browser context is not started");
    const page = await this.context.newPage();
    try {
      try {
        await page.goto(PLANTWARE_CONFIG.entryUrl, { timeout: 30000, waitUntil: "networkidle" });
      } catch {
        await page.goto(PLANTWARE_CONFIG.entryUrl, { timeout: 45000, waitUntil: "domcontentloaded" });
      }
      await page.waitForSelector("#txtUsername", { timeout: 10000 });
      await page.fill("#txtUsername", PLANTWARE_CONFIG.username);
      await page.fill("#txtPassword", PLANTWARE_CONFIG.password);
      await page.click("#btnLogin");
      await page.waitForURL(/Setlocation/i, { timeout: 20000 });
      await page.waitForSelector(`input[value='${PLANTWARE_CONFIG.division}']`, { timeout: 5000 });
      await page.click(`input[value='${PLANTWARE_CONFIG.division}']`, { noWaitAfter: true });
      await page.evaluate(() => {
        const btn = document.getElementById("MainContent_btnOkay");
        if (btn) (btn as HTMLButtonElement).click();
      }).catch((error: unknown) => {
        if (!(error instanceof Error) || !error.message.includes("Execution context was destroyed")) throw error;
      });
      try {
        await page.waitForLoadState("networkidle", { timeout: 10000 });
      } catch {
        await page.waitForTimeout(3000);
      }
      await page.waitForURL(/frmPrTrxADLists/i, { timeout: 10000 }).catch(() => {});
      await this.saveSession();
      this.sessionReused = false;
    } finally {
      await page.close().catch(() => {});
    }
  }

  async tryLoadSession(): Promise<boolean> {
    const sessionPath = this.sessionPath();
    if (!this.browser || !fs.existsSync(sessionPath)) return false;
    try {
      const sessionData = JSON.parse(fs.readFileSync(sessionPath, "utf-8"));
      if (!sessionData.storageState?.cookies?.length) return false;
      const savedAt = new Date(sessionData.savedAt);
      const ageMinutes = (Date.now() - savedAt.getTime()) / 60000;
      if (ageMinutes > 240) return false;
      const testContext = await this.browser.newContext({
        storageState: sessionData.storageState,
        viewport: { width: 1280, height: 720 }
      });
      const testPage = await testContext.newPage();
      await testPage.goto(`${PLANTWARE_CONFIG.baseUrl}${PLANTWARE_CONFIG.listPage}`, {
        timeout: 15000,
        waitUntil: "domcontentloaded"
      });
      const url = testPage.url();
      const authenticated = await this.isAuthenticatedPlantwarePage(testPage);
      await testPage.close().catch(() => {});
      if (url.includes("login") || url.includes("Login") || url.includes("SessionExpire") || !authenticated) {
        await testContext.close().catch(() => {});
        return false;
      }
      await this.context?.close().catch(() => {});
      this.context = testContext;
      this.sessionReused = true;
      return true;
    } catch {
      return false;
    }
  }

  async saveSession(): Promise<void> {
    if (!this.context) throw new Error("Browser context is not started");
    const sessionPath = this.sessionPath();
    fs.mkdirSync(path.dirname(sessionPath), { recursive: true });
    const storageState = await this.context.storageState();
    fs.writeFileSync(sessionPath, JSON.stringify({
      sessionId: this.sessionId,
      savedAt: new Date().toISOString(),
      storageState
    }, null, 2));
  }

  async close(): Promise<void> {
    await this.context?.close().catch(() => {});
    await this.browser?.close().catch(() => {});
    this.context = null;
    this.browser = null;
  }

  private async isAuthenticatedPlantwarePage(page: Page): Promise<boolean> {
    const url = page.url();
    if (/login|SessionExpire/i.test(url)) return false;
    const bodyText = await page.locator("body").textContent({ timeout: 3000 }).catch(() => "");
    if (/login|session expired/i.test(bodyText ?? "")) return false;
    return await page.locator("#MainContent_btnNew, input[id*='btnNew'], a[href*='frmPrTrxADDets'], body:has-text('Manual Adjustment')").first().isVisible({ timeout: 5000 }).catch(() => false);
  }

  private sessionPath(): string {
    return path.join(this.sessionDir, `${this.sessionId}.json`);
  }
}
