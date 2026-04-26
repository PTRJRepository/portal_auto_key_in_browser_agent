import { dirname } from "node:path";
import { mkdirSync } from "node:fs";
import type { Page } from "playwright";

export interface ScreenshotOptions {
  outputDir: string;
  prefix: string;
}

export const DEFAULT_SCREENSHOT_OPTIONS: ScreenshotOptions = {
  outputDir: "./screenshots",
  prefix: "failure"
};

export async function captureFailureScreenshot(
  page: Page,
  stepId: string,
  stepLabel: string,
  options: Partial<ScreenshotOptions> = {}
): Promise<string> {
  const opts = { ...DEFAULT_SCREENSHOT_OPTIONS, ...options };

  try {
    mkdirSync(opts.outputDir, { recursive: true });
  } catch {
    // Directory may already exist
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `${opts.prefix}_${stepId}_${timestamp}.png`;
  const filepath = `${opts.outputDir}/${filename}`;

  try {
    await page.screenshot({ path: filepath, fullPage: true });
    return filepath;
  } catch {
    try {
      await page.screenshot({ path: filepath, fullPage: false });
      return filepath;
    } catch {
      return "";
    }
  }
}