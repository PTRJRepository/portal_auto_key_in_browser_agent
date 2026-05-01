import type { DeleteDuplicateRowResult, DuplicateDocIdTarget, RunPayload, RunResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { deleteVisibleDocId, findVisibleTargetMatches, goToNextListPage, gotoListPage, targetKey, visibleDocumentRows } from "../plantware/duplicate-docids.js";

type Emit = (event: Record<string, unknown>) => void;

const DUPLICATE_CLEANUP_CATEGORIES = new Set([
  "spsi",
  "masa_kerja",
  "tunjangan_jabatan",
  "premi",
  "premi_tunjangan",
  "potongan_upah_kotor",
  "koreksi",
  "potongan_upah_bersih"
]);
const MAX_DUPLICATE_SCAN_PAGES = 100;

export function duplicateCleanupCategorySupported(categoryKey: string | null | undefined): boolean {
  return DUPLICATE_CLEANUP_CATEGORIES.has(String(categoryKey ?? "").trim().toLowerCase());
}

export async function runDeleteDuplicates(payload: RunPayload, emit: Emit): Promise<RunResult> {
  const started = new Date().toISOString();
  const dryRun = payload.delete_dry_run ?? true;
  const targets = (payload.duplicate_targets ?? []).filter((target) => target.action.toUpperCase() === "DELETE_OLD" && target.doc_id);
  const rows: DeleteDuplicateRowResult[] = [];
  let deletedRows = 0;
  let dryRunRows = 0;
  let notFoundRows = 0;
  let failedRows = 0;

  emit({ event: "duplicate.run.started", total_targets: targets.length, dry_run: dryRun, max_pages: MAX_DUPLICATE_SCAN_PAGES, message: `Duplicate cleanup started for ${targets.length} targets, max scan ${MAX_DUPLICATE_SCAN_PAGES} pages` });

  if (!duplicateCleanupCategorySupported(payload.category_key)) {
    throw new Error(`Duplicate cleanup is not enabled for category ${payload.category_key}`);
  }

  const session = new BrowserSession({
    headless: payload.headless,
    freshLoginFirst: payload.runner_mode === "fresh_login_single",
    division: payload.division_code
  });

  try {
    await session.start();
    emit({ event: "session.ready", reused: session.sessionReused, session_path: session.getSessionPath(), message: session.sessionReused ? "Session reused" : "Fresh session login completed" });
    const page = await session.newPage();
    await gotoListPage(page);

    const pending = new Map(targets.map((target) => [targetKey(target), target]));
    let pageIndex = 1;
    let rescanAttempts = 0;

    while (pending.size) {
      const pendingDocIds = new Set(pending.keys());
      const visibleRows = await visibleDocumentRows(page);
      emit({ event: "duplicate.page.scanned", page_index: pageIndex, visible_count: visibleRows.length, pending_count: pending.size, visible_rows: visibleRows.slice(0, 10), pending_keys: [...pendingDocIds].slice(0, 10), message: `Scanned duplicate list page ${pageIndex}: visible=${visibleRows.length}, pending=${pending.size}` });

      const visibleMatches = await findVisibleTargetMatches(page, pendingDocIds);
      if (dryRun) {
        for (const match of visibleMatches) {
          const target = pending.get(match.key) as DuplicateDocIdTarget | undefined;
          if (!target) continue;
          pending.delete(match.key);
          emit({ event: "duplicate.target.matched", doc_id: target.doc_id, master_id: target.master_id, emp_code: target.emp_code, doc_desc: target.doc_desc, page_index: pageIndex, plantware_row: match.row, message: `Matched target ${target.doc_id}/${target.master_id} with Plantware row ${match.row.docId}/${match.row.masterId}` });
          dryRunRows += 1;
          const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "dry_run", message: "dry-run: target found, delete skipped", page_index: pageIndex };
          rows.push(row);
          emit({ event: "duplicate.target.dry_run", ...row, master_id: target.master_id, plantware_row: match.row });
        }
      } else {
        const match = visibleMatches[0];
        if (match) {
          const target = pending.get(match.key) as DuplicateDocIdTarget;
          pending.delete(match.key);
          emit({ event: "duplicate.target.matched", doc_id: target.doc_id, master_id: target.master_id, emp_code: target.emp_code, doc_desc: target.doc_desc, page_index: pageIndex, plantware_row: match.row, message: `Matched target ${target.doc_id}/${target.master_id} with Plantware row ${match.row.docId}/${match.row.masterId}` });
          try {
            emit({ event: "duplicate.target.delete.started", doc_id: target.doc_id, master_id: target.master_id, emp_code: target.emp_code, page_index: pageIndex, plantware_row: match.row, message: `Deleting duplicate ${target.doc_id}` });
            await deleteVisibleDocId(page, target, (debugEvent) => emit({ event: "duplicate.delete.debug", doc_id: target.doc_id, master_id: target.master_id, page_index: pageIndex, plantware_row: match.row, ...debugEvent, message: `Delete debug ${target.doc_id}: ${String(debugEvent.step ?? "step")}` }));
            deletedRows += 1;
            const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "deleted", message: "deleted", page_index: pageIndex };
            rows.push(row);
            emit({ event: "duplicate.target.deleted", ...row, master_id: target.master_id, plantware_row: match.row });
          } catch (error) {
            failedRows += 1;
            const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "failed", message: error instanceof Error ? error.message : String(error), page_index: pageIndex };
            rows.push(row);
            emit({ event: "duplicate.target.failed", ...row, master_id: target.master_id, plantware_row: match.row });
          }
          await gotoListPage(page);
          pageIndex = 1;
          continue;
        }
      }

      if (pageIndex >= MAX_DUPLICATE_SCAN_PAGES) {
        if (!dryRun && rescanAttempts < 2) {
          rescanAttempts += 1;
          emit({ event: "duplicate.rescan.started", attempt: rescanAttempts, pending_count: pending.size, message: `Rescanning from page 1 for ${pending.size} pending duplicate targets` });
          await gotoListPage(page);
          pageIndex = 1;
          continue;
        }
        break;
      }
      const moved = await goToNextListPage(page);
      if (!moved) {
        if (!dryRun && rescanAttempts < 2) {
          rescanAttempts += 1;
          emit({ event: "duplicate.rescan.started", attempt: rescanAttempts, pending_count: pending.size, message: `Reached end of list; rescanning from page 1 for ${pending.size} pending duplicate targets` });
          await gotoListPage(page);
          pageIndex = 1;
          continue;
        }
        break;
      }
      pageIndex += 1;
    }

    for (const target of pending.values()) {
      notFoundRows += 1;
      const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "not_found", message: "target DocID not found on Plantware list", page_index: pageIndex };
      rows.push(row);
      emit({ event: "duplicate.target.not_found", ...row });
    }

    emit({ event: "duplicate.run.completed", deleted_rows: deletedRows, dry_run_rows: dryRunRows, not_found_rows: notFoundRows, failed_rows: failedRows, message: `Duplicate cleanup completed: deleted=${deletedRows}, dry_run=${dryRunRows}, not_found=${notFoundRows}, failed=${failedRows}` });

    return {
      success: failedRows === 0,
      started_at: started,
      finished_at: new Date().toISOString(),
      runner_mode: payload.runner_mode,
      session_reused: session.sessionReused,
      total_records: targets.length,
      attempted_rows: rows.length,
      inserted_rows: 0,
      skipped_existing_rows: dryRunRows + notFoundRows,
      failed_rows: failedRows,
      deleted_rows: deletedRows,
      dry_run_rows: dryRunRows,
      not_found_rows: notFoundRows,
      error_summary: failedRows ? `${failedRows} duplicate deletes failed` : null,
      rows
    };
  } finally {
    await session.close();
  }
}
