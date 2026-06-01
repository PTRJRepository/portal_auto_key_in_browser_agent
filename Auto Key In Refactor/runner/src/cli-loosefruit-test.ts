#!/usr/bin/env node
/**
 * Headfull test CLI for loosefruit duplicate deletion.
 * Usage:
 *   npx ts-node src/cli-loosefruit-test.ts --dry-run --doc-id "DOC123"
 *   npx ts-node src/cli-loosefruit-test.ts --inspect --doc-id "DOC123"
 *   npx ts-node src/cli-loosefruit-test.ts --list-duplicates
 */
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { LOOSEFRUIT_LIST_URL, gotoLoosefruitPage, deleteLoosefruitDocId } from "./plantware/loosefruit-duplicates.js"
import { BrowserSession } from "./session/browser-session.js";

interface Args {
  dryRun: boolean;
  inspect: boolean;
  listDuplicates: boolean;
  docId?: string;
  locCode?: string;
}

function parseArgs(): Args {
  const args = process.argv.slice(2);
  return {
    dryRun: args.includes("--dry-run"),
    inspect: args.includes("--inspect"),
    listDuplicates: args.includes("--list-duplicates"),
    docId: extractArg(args, "--doc-id"),
    locCode: extractArg(args, "--loc-code"),
  };
}

function extractArg(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  return idx >= 0 ? args[idx + 1] : undefined;
}

async function main() {
  const opts = parseArgs();

  console.log("=== Loosefruit Headfull Test ===");
  console.log(`URL: ${LOOSEFRUIT_LIST_URL}`);
  console.log(`Dry run: ${opts.dryRun}`);
  console.log(`Inspect: ${opts.inspect}`);
  console.log(`DocID: ${opts.docId ?? "(none)"}`);
  console.log(`LocCode: ${opts.locCode ?? "(none)"}`);
  console.log();

  const session = new BrowserSession({ headless: false, division: "P1B" });

  try {
    console.log("[1/3] Starting browser session...");
    await session.start();
    console.log("  ✓ Session ready");

    const page = await session.newPage();

    if (opts.inspect) {
      console.log("\n[INSPECT MODE] Navigating to loosefruit list page...");
      await gotoLoosefruitPage(page);
      console.log("  ✓ Page loaded. Inspect manually in browser.");
      console.log("  Press Ctrl+C to exit when done.");
      await page.waitForTimeout(60000);
      return;
    }

    if (opts.listDuplicates) {
      console.log("\n[LIST MODE] Finding all duplicate DocIDs (underscore pattern)...");
      await gotoLoosefruitPage(page);
      await page.waitForTimeout(3000);
      const snapshot = await page.locator("body").textContent() || "";
      console.log(snapshot.substring(0, 1000));
      await page.waitForTimeout(10000);
      return;
    }

    if (opts.docId) {
      console.log(`\n[TEST MODE] Testing DocID: ${opts.docId}`);
      const outcome = await deleteLoosefruitDocId(page, opts.docId, opts.dryRun);
      console.log(`  Result: ${outcome.success ? "✓" : "✗"} ${outcome.message}`);
      await page.waitForTimeout(2000);
    } else {
      console.log("\nNo --doc-id or --inspect specified. Use --help for usage.");
    }

  } catch (err) {
    console.error("Error:", err);
    process.exit(1);
  } finally {
    await session.close();
    console.log("\nSession closed.");
  }
}

main();
