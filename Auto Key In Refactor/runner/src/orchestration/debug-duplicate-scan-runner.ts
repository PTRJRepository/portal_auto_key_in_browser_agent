import type { DeleteDuplicateRowResult, DuplicateDocIdTarget, RunPayload, RunResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { findVisibleTargetMatches, goToNextListPage, gotoListPage, targetKey, visibleDocumentRows } from "../plantware/duplicate-docids.js";

type Emit = (event: Record<string, unknown>) => void;

const MAX_DEBUG_SCAN_PAGES = 500;

export async function runDebugDuplicateScan(payload: RunPayload, emit: Emit): Promise<RunResult> {
  const started = new Date().toISOString();
  const targets = (payload.duplicate_targets ?? []).filter((target) => target.action.toUpperCase() === "DELETE_OLD" && target.doc_id);
  const pending = new Map(targets.map((target) => [targetKey(target), target]));
  const rows: DeleteDuplicateRowResult[] = [];
  const matchedKeys = new Set<string>();

  emit({ event: "duplicate.debug.started", division_code: payload.division_code, total_targets: targets.length, max_pages: MAX_DEBUG_SCAN_PAGES, target_keys: [...pending.keys()].slice(0, 50), message: `Debug duplicate scan started for ${payload.division_code}: targets=${targets.length}, max_pages=${MAX_DEBUG_SCAN_PAGES}` });

  const session = new BrowserSession({
    headless: payload.headless,
    freshLoginFirst: payload.runner_mode === "fresh_login_single",
    division: payload.division_code
  });

  let pageIndex = 1;
  try {
    await session.start();
    emit({ event: "session.ready", reused: session.sessionReused, session_path: session.getSessionPath(), message: session.sessionReused ? "Session reused" : "Fresh session login completed" });
    const page = await session.newPage();
    await gotoListPage(page);

    while (pageIndex <= MAX_DEBUG_SCAN_PAGES) {
      const pendingKeys = new Set([...pending.keys()].filter((key) => !matchedKeys.has(key)));
      const visibleRows = await visibleDocumentRows(page);
      const visibleKeys = visibleRows.flatMap((row) => {
        const keys = [`DOC:${row.docId.replace(/\s+/g, "").trim().toUpperCase()}`];
        if (row.masterId) keys.unshift(`MASTER:${row.masterId.trim()}`);
        return keys;
      });
      const matches = await findVisibleTargetMatches(page, pendingKeys);

      emit({
        event: "duplicate.debug.page",
        page_index: pageIndex,
        url: page.url(),
        visible_count: visibleRows.length,
        pending_count: pendingKeys.size,
        matched_count: matches.length,
        visible_rows: visibleRows,
        visible_keys: visibleKeys,
        pending_keys_sample: [...pendingKeys].slice(0, 50),
        message: `Debug page ${pageIndex}: visible=${visibleRows.length}, matches=${matches.length}, pending=${pendingKeys.size}`
      });

      for (const match of matches) {
        const target = pending.get(match.key) as DuplicateDocIdTarget | undefined;
        if (!target || matchedKeys.has(match.key)) continue;
        matchedKeys.add(match.key);
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "dry_run", message: `debug matched ${match.key} on page ${pageIndex}`, page_index: pageIndex };
        rows.push(row);
        emit({ event: "duplicate.debug.matched", key: match.key, target, plantware_row: match.row, page_index: pageIndex, message: `Debug matched API target ${target.doc_id}/${target.master_id} to Plantware row ${match.row.docId}/${match.row.masterId} on page ${pageIndex}` });
      }

      const moved = await goToNextListPage(page);
      if (!moved) {
        emit({ event: "duplicate.debug.end_of_pages", page_index: pageIndex, message: `No next page after page ${pageIndex}` });
        break;
      }
      pageIndex += 1;
    }

    for (const [key, target] of pending.entries()) {
      if (matchedKeys.has(key)) continue;
      const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "not_found", message: `debug not found after ${pageIndex} pages (${key})`, page_index: pageIndex };
      rows.push(row);
      emit({ event: "duplicate.debug.not_found", key, target, pages_checked: pageIndex, message: `Debug did not find API target ${target.doc_id}/${target.master_id} after ${pageIndex} pages` });
    }

    emit({ event: "duplicate.debug.completed", matched_rows: matchedKeys.size, not_found_rows: pending.size - matchedKeys.size, pages_checked: pageIndex, message: `Debug duplicate scan completed: matched=${matchedKeys.size}, not_found=${pending.size - matchedKeys.size}, pages=${pageIndex}` });

    return {
      success: true,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: session.sessionReused,
      total_records: targets.length,
      attempted_rows: rows.length,
      inserted_rows: 0,
      skipped_existing_rows: rows.length,
      failed_rows: 0,
      dry_run_rows: matchedKeys.size,
      not_found_rows: pending.size - matchedKeys.size,
      error_summary: null,
      rows
    };
  } finally {
    await session.close();
  }
}
