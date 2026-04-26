import type { Page, Locator } from "playwright";

export interface RetryOptions {
  maxAttempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  backoffMultiplier: number;
}

export interface StableElementOptions {
  state?: "visible" | "attached" | "hidden" | "detached";
  timeoutMs: number;
}

export const DEFAULT_RETRY_OPTIONS: RetryOptions = {
  maxAttempts: 3,
  baseDelayMs: 200,
  maxDelayMs: 5000,
  backoffMultiplier: 2
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  options: Partial<RetryOptions> = {}
): Promise<T> {
  const opts = { ...DEFAULT_RETRY_OPTIONS, ...options };
  let lastError: Error;

  for (let attempt = 1; attempt <= opts.maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < opts.maxAttempts) {
        const delay = Math.min(
          opts.baseDelayMs * Math.pow(opts.backoffMultiplier, attempt - 1),
          opts.maxDelayMs
        );
        await sleep(delay);
      }
    }
  }
  throw lastError!;
}

export async function waitForNetworkIdle(
  page: Page,
  timeoutMs: number = 10000
): Promise<void> {
  try {
    await page.waitForLoadState("networkidle", { timeout: timeoutMs });
  } catch {
    await page.waitForLoadState("domcontentloaded");
  }
}

export async function waitForStableElement(
  page: Page,
  selector: string,
  options: Partial<StableElementOptions> = {}
): Promise<Locator> {
  const state = options.state ?? "visible";
  const timeoutMs = options.timeoutMs ?? 15000;

  const locator = page.locator(selector).first();
  await locator.waitFor({ state, timeout: timeoutMs });
  await page.waitForTimeout(50);

  return locator;
}