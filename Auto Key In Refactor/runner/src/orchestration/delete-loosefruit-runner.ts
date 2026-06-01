import type { Page } from "playwright";
import type { DeleteLoosefruitRowResult, DuplicateDocIdTarget, LoosefruitTarget, RunPayload, RunResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { sessionDivisionCode } from "../payload.js";
import { deleteLoosefruitDocId, gotoLoosefruitListPage, searchLoosefruitByDocId } from "../plantware/loosefruit-page.js";
import { loosefruitListUrl } from "../plantware/loosefruit-page.js";

type Emit = (event: Record<string, unknown>) => void;
type LoosefruitPayload = RunPayload & { targets?: LoosefruitTarget[]; loosefruit_targets?: LoosefruitTarget[] };

const LOOSEFRUIT_SOURCE = "loosefruit-pr-loosefruit";
const DELETE_LOOSEFRUIT_ACTIONS = new Set(["DELETE_RECORD", "DELETE_OLD"]);
const TARGETS_PER_PAGE_REFRESH = 5;

export function isLoosefruitDuplicateTarget(target: DuplicateDocIdTarget): boolean {
  const category = String(target.category ?? "").trim().toLowerCase();
  const source = String(target.raw?.source ?? "").trim().toLowerCase();
  const table = String(target.raw?.table ?? "").trim().toLowerCase();
  return category === "loosefruit" || source === LOOSEFRUIT_SOURCE || table.includes("pr_loosefruit");
}

export function loosefruitTargetLocCode(target: LoosefruitTarget | DuplicateDocIdTarget): string {
  const raw = target.raw ?? {};
  const directLocCode = "loc_code" in target ? target.loc_code : "";
  return String(directLocCode || raw.loc_code || raw.locCode || raw.LocCode || "").trim().toUpperCase();
}

export function loosefruitTargetFromDuplicateTarget(target: DuplicateDocIdTarget): LoosefruitTarget {
  return {
    doc_id: target.doc_id,
    master_id: target.master_id || null,
    loc_code: loosefruitTargetLocCode(target),
    doc_date: target.doc_date || null,
    action: target.action,
    raw: target.raw
  };
}

export function loosefruitTargetsFromPayload(payload: LoosefruitPayload): LoosefruitTarget[] {
  const explicitTargets = payload.targets ?? payload.loosefruit_targets;
  if (explicitTargets) {
    return explicitTargets.filter((target) => target.doc_id && DELETE_LOOSEFRUIT_ACTIONS.has(String(target.action ?? "").trim().toUpperCase()));
  }
  return (payload.duplicate_targets ?? [])
    .filter((target) => isLoosefruitDuplicateTarget(target))
    .filter((target) => target.doc_id && DELETE_LOOSEFRUIT_ACTIONS.has(String(target.action ?? "").trim().toUpperCase()))
    .map(loosefruitTargetFromDuplicateTarget);
}

export function loosefruitTargetsByLocCode(payload: RunPayload, targets: LoosefruitTarget[]): Map<string, LoosefruitTarget[]> {
  const fallbackLocCode = sessionDivisionCode(payload);
  const groups = new Map<string, LoosefruitTarget[]>();
  for (const target of targets) {
    const locCode = loosefruitTargetLocCode(target) || fallbackLocCode;
    if (!locCode) continue;
    groups.set(locCode, [...(groups.get(locCode) ?? []), { ...target, loc_code: target.loc_code || locCode }]);
  }
  return groups;
}

function targetWithFoundMasterId(target: LoosefruitTarget, found: { masterId: string; locCode: string }): LoosefruitTarget {
  return {
    ...target,
    master_id: target.master_id || found.masterId || null,
    loc_code: target.loc_code || found.locCode
  };
}

function processLoosefruitTarget(
  page: Awaited<ReturnType<BrowserSession["newPage"]>>,
  target: LoosefruitTarget,
  locCode: string,
  dryRun: boolean,
  tabIndex: number,
  emit: Emit,
): Promise<DeleteLoosefruitRowResult> {
  return (async () => {
    emit({ event: "loosefruit.search.started", doc_id: target.doc_id, loc_code: locCode, message: "Searching Loosefruit DocID " + target.doc_id });

    const found = await searchLoosefruitByDocId(page, target);
    if (!found) {
      const row: DeleteLoosefruitRowResult = { doc_id: target.doc_id, master_id: target.master_id, loc_code: locCode, status: "not_found", message: "Loosefruit DocID not found after search", page_index: tabIndex };
      emit({ event: "loosefruit.target.not_found", ...row });
      return row;
    }

    const deleteTarget = targetWithFoundMasterId(target, found);
    emit({ event: "loosefruit.target.matched", doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, loc_code: locCode, plantware_row: found, message: "Matched Loosefruit DocID " + deleteTarget.doc_id });
    if (dryRun) {
      const row: DeleteLoosefruitRowResult = { doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, loc_code: locCode, status: "dry_run", message: "dry-run: Loosefruit target found, delete skipped", page_index: tabIndex };
      emit({ event: "loosefruit.target.dry_run", ...row, plantware_row: found });
      return row;
    }

    try {
      emit({ event: "loosefruit.target.delete.started", doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, loc_code: locCode, message: "Deleting Loosefruit DocID " + deleteTarget.doc_id });
      const log = (event: Record<string, unknown>) => emit({ event: "loosefruit.delete.debug", doc_id: deleteTarget.doc_id, loc_code: locCode, ...event, message: "Loosefruit delete debug " + deleteTarget.doc_id + ": " + String(event.step ?? "step") });
      await deleteLoosefruitDocId(page, deleteTarget, log);
      await gotoLoosefruitListPage(page);
      const stillVisible = await searchLoosefruitByDocId(page, deleteTarget);
      if (stillVisible) {
        throw new Error("Loosefruit DocID " + deleteTarget.doc_id + " still visible after delete attempt");
      }
      const row: DeleteLoosefruitRowResult = { doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, loc_code: locCode, status: "deleted", message: "deleted and verified absent from Loosefruit list", page_index: tabIndex };
      emit({ event: "loosefruit.target.deleted", ...row });
      return row;
    } catch (error) {
      const row: DeleteLoosefruitRowResult = { doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, loc_code: locCode, status: "failed", message: error instanceof Error ? error.message : String(error), page_index: tabIndex };
      emit({ event: "loosefruit.target.failed", ...row });
      await gotoLoosefruitListPage(page).catch(() => {});
      return row;
    }
  })();
}

async function processLoosefruitTab(
  session: BrowserSession,
  page: Page,
  sessionDivision: string,
  locCode: string,
  locCodes: string[],
  targets: LoosefruitTarget[],
  dryRun: boolean,
  tabIndex: number,
  emit: Emit,
): Promise<DeleteLoosefruitRowResult[]> {
  const tabRows: DeleteLoosefruitRowResult[] = [];

  async function ensureFreshPage(): Promise<Page> {
    const p = await session.newPage();
    await gotoLoosefruitListPage(p);
    emit({ event: "loosefruit.list.page.reloaded", tab_index: tabIndex, loc_code: locCode, url: p.url() });
    return p;
  }

  let activePage = page;
  emit({ event: "loosefruit.tab.started", tab_index: tabIndex, loc_code: locCode, loc_codes: locCodes, total_targets: targets.length });

  for (let i = 0; i < targets.length; i++) {
    const target = targets[i];

    // refresh page setiap TARGETS_PER_PAGE_REFRESH target biar speed konsisten
    if (i > 0 && i % TARGETS_PER_PAGE_REFRESH === 0) {
      emit({ event: "loosefruit.tab.refreshing", tab_index: tabIndex, loc_code: locCode, processed: i, total: targets.length, message: "Refreshing page at target " + (i + 1) + "/" + targets.length + " to maintain speed" });
      await activePage.close().catch(() => {});
      activePage = await ensureFreshPage();
    }

    const targetLocCode = loosefruitTargetLocCode(target) || sessionDivision;
    const row = await processLoosefruitTarget(activePage, target, targetLocCode, dryRun, tabIndex, emit);
    tabRows.push(row);
  }

  emit({ event: "loosefruit.tab.completed", tab_index: tabIndex, loc_code: locCode });
  return tabRows;
}

export async function runDeleteLoosefruit(payload: RunPayload, emit: Emit): Promise<RunResult> {
  const started = new Date().toISOString();
  const dryRun = payload.delete_dry_run ?? true;
  const targets = loosefruitTargetsFromPayload(payload as LoosefruitPayload);
  const rows: DeleteLoosefruitRowResult[] = [];
  let sessionReused = false;

  // distribute all targets round-robin across max_tabs
  const maxTabs = Math.max(1, payload.max_tabs || 1);
  const tabEntries: Array<{ locCodes: string[]; targets: LoosefruitTarget[] }> = Array.from({ length: maxTabs }, () => ({ locCodes: [], targets: [] }));
  const flatTargets = targets.filter((t) => loosefruitTargetLocCode(t) || sessionDivisionCode(payload));
  for (let i = 0; i < flatTargets.length; i++) {
    const tabIdx = i % maxTabs;
    const locCode = loosefruitTargetLocCode(flatTargets[i]) || sessionDivisionCode(payload);
    tabEntries[tabIdx].targets.push(flatTargets[i]);
    if (locCode && !tabEntries[tabIdx].locCodes.includes(locCode)) {
      tabEntries[tabIdx].locCodes.push(locCode);
    }
  }

  const missingLocCodeTargets = targets.filter((target) => !loosefruitTargetLocCode(target) && !sessionDivisionCode(payload));
  for (const target of missingLocCodeTargets) {
    const row: DeleteLoosefruitRowResult = { doc_id: target.doc_id, master_id: target.master_id, loc_code: "", status: "failed", message: "Loosefruit target has no LocCode and no payload session division", page_index: 0 };
    rows.push(row);
    emit({ event: "loosefruit.target.failed", ...row });
  }

  const uniqueLocCodes = [...new Set(flatTargets.map((t) => loosefruitTargetLocCode(t) || sessionDivisionCode(payload)).filter(Boolean))];
  emit({ event: "loosefruit.run.started", total_targets: targets.length, dry_run: dryRun, loc_codes: uniqueLocCodes, max_tabs: maxTabs, message: "Loosefruit duplicate cleanup started for " + targets.length + " targets across " + uniqueLocCodes.length + " LocCode(s) with " + maxTabs + " tab(s)" });

  if (flatTargets.length === 0) {
    const failedRows = rows.filter((r) => r.status === "failed").length;
    emit({ event: "loosefruit.run.completed", deleted_rows: 0, dry_run_rows: 0, not_found_rows: 0, failed_rows: failedRows, message: "Loosefruit cleanup completed: no targets to process" });
    return {
      success: failedRows === 0,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: false,
      total_records: 0,
      attempted_rows: rows.length,
      inserted_rows: 0,
      skipped_existing_rows: rows.filter((r) => r.status === "dry_run" || r.status === "not_found").length,
      failed_rows: failedRows,
      deleted_rows: 0,
      dry_run_rows: 0,
      not_found_rows: 0,
      error_summary: failedRows ? String(failedRows) + " Loosefruit deletes failed" : null,
      rows
    };
  }

  const sessionDivision = sessionDivisionCode(payload);
  const session = new BrowserSession({
    headless: payload.headless,
    freshLoginFirst: false,
    loginFallback: true,
    division: sessionDivision
  });

  try {
    await session.start();
    sessionReused = session.sessionReused;
    emit({ event: "session.ready", division_code: payload.division_code, session_division_code: sessionDivision, reused: session.sessionReused, session_path: session.getSessionPath(), message: session.sessionReused ? "Session reused" : "Fresh session login completed" });

    // Create all pages SEQUENTIALLY — satu per satu, biar ga overload Plantware
    const tabPages: Page[] = [];
    for (const entry of tabEntries) {
      const primaryLocCode = entry.locCodes[0] || sessionDivision;
      const page = await session.newPage();
      await gotoLoosefruitListPage(page);
      emit({ event: "loosefruit.list.page.loaded", tab_index: tabPages.length, loc_code: primaryLocCode, url: page.url() });
      tabPages.push(page);
    }

    const tabResults = await Promise.allSettled(
      tabEntries.map(async (entry, tabIndex) => {
        const primaryLocCode = entry.locCodes[0] || sessionDivision;
        return processLoosefruitTab(session, tabPages[tabIndex], sessionDivision, primaryLocCode, entry.locCodes, entry.targets, dryRun, tabIndex, emit);
      })
    );

    for (let i = 0; i < tabResults.length; i++) {
      const result = tabResults[i];
      const entry = tabEntries[i];
      const primaryLocCode = entry.locCodes[0] || sessionDivision;
      if (result.status === "fulfilled") {
        rows.push(...result.value);
      } else {
        const message = result.reason instanceof Error ? result.reason.message : String(result.reason);
        emit({ event: "loosefruit.tab.failed", tab_index: i, loc_codes: entry.locCodes, message });
        for (const target of entry.targets) {
          const row: DeleteLoosefruitRowResult = { doc_id: target.doc_id, master_id: target.master_id, loc_code: loosefruitTargetLocCode(target) || primaryLocCode, status: "failed", message, page_index: i };
          rows.push(row);
          emit({ event: "loosefruit.target.failed", ...row });
        }
      }
    }

    // Clean up all pages
    await Promise.allSettled(tabPages.map((p) => p.close().catch(() => {})));

  } finally {
    await session.close();
  }

  const deletedRows = rows.filter((r) => r.status === "deleted").length;
  const dryRunRows = rows.filter((r) => r.status === "dry_run").length;
  const notFoundRows = rows.filter((r) => r.status === "not_found").length;
  const failedRows = rows.filter((r) => r.status === "failed").length;

  emit({ event: "loosefruit.run.completed", deleted_rows: deletedRows, dry_run_rows: dryRunRows, not_found_rows: notFoundRows, failed_rows: failedRows, message: "Loosefruit cleanup completed: deleted=" + deletedRows + ", dry_run=" + dryRunRows + ", not_found=" + notFoundRows + ", failed=" + failedRows });

  return {
    success: failedRows === 0,
    started_at: started,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused: sessionReused,
    total_records: targets.length,
    attempted_rows: rows.length,
    inserted_rows: 0,
    skipped_existing_rows: dryRunRows + notFoundRows,
    failed_rows: failedRows,
    deleted_rows: deletedRows,
    dry_run_rows: dryRunRows,
    not_found_rows: notFoundRows,
    error_summary: failedRows ? String(failedRows) + " Loosefruit deletes failed" : null,
    rows
  };
}
