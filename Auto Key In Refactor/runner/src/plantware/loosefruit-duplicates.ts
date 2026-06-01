import type { Page } from "playwright";

export const LOOSEFRUIT_LIST_URL =
  "http://plantwarep3:8001/en/PR/trx/frmPrTrxLooseFruitList.aspx";

export interface LoosefruitTarget {
  id: string;
  doc_id: string;
  doc_date: string;
  loc_code: string;
  status: string;
  total_mt?: number | null;
  doc_desc?: string;
}

export async function gotoLoosefruitPage(page: Page): Promise<void> {
  await page.goto(LOOSEFRUIT_LIST_URL, { waitUntil: "networkidle" });
  await page.waitForLoadState("domcontentloaded");
}

export async function searchLoosefruitByDocId(
  page: Page,
  docId: string,
): Promise<boolean> {
  const searchInput = page.locator("input[id$='txtDocID']," +
    "input[id*='DocID']," +
    "input[id*='docid']," +
    "input[name*='DocID']," +
    "input[placeholder*='Doc']");
  if (await searchInput.count() === 0) {
    // try generic search
    const anySearch = page.locator("input[type='search'], input[id*='Search'], input[id*='search']");
    if (await anySearch.count() > 0) {
      await anySearch.first().fill(docId);
    } else {
      throw new Error(`No search input found for DocID: ${docId}`);
    }
  } else {
    await searchInput.first().fill(docId);
  }

  // Click search/filter button
  const searchBtn = page.locator(
    "input[id$='btnSearch']," +
    "button[id$='btnSearch']," +
    "input[id*='btnSearch']," +
    "button[id*='Search']," +
    "input[value*='Search']," +
    "input[value*='Cari']",
  );
  if (await searchBtn.count() > 0) {
    await searchBtn.first().click();
    await page.waitForTimeout(500);
  }
  return true;
}

export async function findAndClickDeleteButton(
  page: Page,
  docId: string,
): Promise<boolean> {
  // Try to find the row with matching DocID
  const row = page.locator(
    `tr[id*='grd'] td:text("${docId}"),` +
    `tr[id*='Grid'] td:text("${docId}"),` +
    `tr td:text-is("${docId}")`,
  );

  if (await row.count() === 0) {
    return false;
  }

  // Find delete button in the same row or nearby
  const deleteBtn = row.locator(
    "..//input[@value='Delete']," +
    "..//button[contains(text(),'Delete')]," +
    "..//a[contains(text(),'Delete')]," +
    "..//input[@value='Hapus']," +
    "..//button[contains(text(),'Hapus')]",
  );

  if (await deleteBtn.count() > 0) {
    await deleteBtn.first().click();
    // Handle confirmation dialog if any
    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });
    await page.waitForTimeout(300);
    return true;
  }

  // Alternative: click delete in the row's action column
  const actionDelete = page.locator(
    `tr:has(td:text("${docId}")) input[value='Delete'],` +
    `tr:has(td:text("${docId}")) button:has-text("Delete"),` +
    `tr:has(td:text("${docId}")) a:has-text("Delete")`,
  );
  if (await actionDelete.count() > 0) {
    await actionDelete.first().click();
    await page.waitForTimeout(300);
    return true;
  }

  return false;
}

/**
 * Open detail view for a loosefruit record by clicking its link.
 * Returns true if detail was opened, false if not found.
 */
export async function openLoosefruitDetail(
  page: Page,
  docId: string,
): Promise<boolean> {
  // Find the row or link containing the docId and click it
  const detailLink = page.locator(
    `a:has-text("${docId}"),` +
    `td:text-is("${docId}") >> xpath=ancestor::tr//a | //input[@type='image'][@alt*='Detail'],` +
    `tr:has(td:text("${docId}")) a:has-text("Detail"),` +
    `tr:has(td:text("${docId}")) img[alt*='Detail'],` +
    `tr:has(td:text("${docId}")) input[type='image'][alt*='etail'],` +
    `tr:has(td:text("${docId}")) a[href*='Detail'],` +
    `tr:has(td:text("${docId}")) a`,
  );
  if (await detailLink.count() > 0) {
    await detailLink.first().click();
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(500);
    return true;
  }
  return false;
}

export async function deleteLoosefruitDocId(
  page: Page,
  docId: string,
  dryRun: boolean = false,
): Promise<{ success: boolean; message: string }> {
  try {
    await gotoLoosefruitPage(page);
    await page.waitForTimeout(1000);
    await searchLoosefruitByDocId(page, docId);
    await page.waitForTimeout(1000);

    // Step 1: Open detail page
    const opened = await openLoosefruitDetail(page, docId);
    if (!opened) {
      return { success: false, message: `Detail not found for DocID: ${docId}` };
    }
    console.log(`  [LOOSEFRUIT] Detail opened for: ${docId}`);

    // Step 2: Click delete on detail page
    const deleteBtn = page.locator(
      "input[value='Delete']," +
      "button:has-text('Delete')," +
      "a:has-text('Delete')," +
      "input[value='Hapus']," +
      "button:has-text('Hapus')",
    );
    if (await deleteBtn.count() === 0) {
      return { success: false, message: `Delete button not found on detail page for: ${docId}` };
    }

    if (dryRun) {
      console.log(`  [LOOSEFRUIT] DRY RUN: would click delete for ${docId}`);
      // Navigate back to list
      await page.goBack();
      return { success: true, message: `Dry run: ${docId} found, delete button present` };
    }

    await deleteBtn.first().click();
    // Accept confirmation dialog if present
    page.once("dialog", async (dialog) => {
      console.log(`  [LOOSEFRUIT] Dialog: "${dialog.message()}"`);
      await dialog.accept();
    });
    await page.waitForTimeout(500);
    return { success: true, message: `Deleted loosefruit: ${docId}` };
  } catch (err) {
    return { success: false, message: `Error deleting ${docId}: ${String(err)}` };
  }
}