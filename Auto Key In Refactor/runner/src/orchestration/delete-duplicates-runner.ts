import type { DeleteDuplicateRowResult, DuplicateDocIdTarget, RunPayload, RunResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { deleteVisibleDocId, gotoListPage, searchVisibleTargetByDocId, type VisibleDocumentRow } from "../plantware/duplicate-docids.js";

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
const DELETE_DOCID_ACTIONS = new Set(["DELETE_OLD", "DELETE_RECORD"]);

export function duplicateCleanupCategorySupported(categoryKey: string | null | undefined): boolean {
  return DUPLICATE_CLEANUP_CATEGORIES.has(String(categoryKey ?? "").trim().toLowerCase());
}

export function deleteDocIdActionSupported(action: string | null | undefined): boolean {
  return DELETE_DOCID_ACTIONS.has(String(action ?? "").trim().toUpperCase());
}

export function targetWithMatchedMasterId(target: DuplicateDocIdTarget, row: VisibleDocumentRow): DuplicateDocIdTarget {
  if (target.master_id || !row.masterId) return target;
  return { ...target, master_id: row.masterId };
}

export async function runDeleteDuplicates(payload: RunPayload, emit: Emit): Promise<RunResult> {
  const started = new Date().toISOString();
  const dryRun = payload.delete_dry_run ?? true;
  const targets = (payload.duplicate_targets ?? []).filter((target) => deleteDocIdActionSupported(target.action) && target.doc_id);
  const rows: DeleteDuplicateRowResult[] = [];
  let deletedRows = 0;
  let dryRunRows = 0;
  let notFoundRows = 0;
  let failedRows = 0;

  emit({ event: "duplicate.run.started", total_targets: targets.length, dry_run: dryRun, max_pages: MAX_DUPLICATE_SCAN_PAGES, message: `Duplicate cleanup started for ${targets.length} targets using DocID search` });

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

    for (const target of targets) {
      emit({ event: "duplicate.search.started", doc_id: target.doc_id, master_id: target.master_id, emp_code: target.emp_code, doc_desc: target.doc_desc, message: `Searching DocID ${target.doc_id}` });
      const match = await searchVisibleTargetByDocId(page, target);
      if (!match) {
        notFoundRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, emp_code: target.emp_code, doc_desc: target.doc_desc, status: "not_found", message: "target DocID not found after Plantware search", page_index: 1 };
        rows.push(row);
        emit({ event: "duplicate.target.not_found", ...row });
        continue;
      }
      const deleteTarget = targetWithMatchedMasterId(target, match.row);
      emit({ event: "duplicate.target.matched", doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, emp_code: deleteTarget.emp_code, doc_desc: deleteTarget.doc_desc, page_index: 1, plantware_row: match.row, message: `Matched target ${deleteTarget.doc_id}/${deleteTarget.master_id} with Plantware row ${match.row.docId}/${match.row.masterId}` });
      if (dryRun) {
        dryRunRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: deleteTarget.doc_id, emp_code: deleteTarget.emp_code, doc_desc: deleteTarget.doc_desc, status: "dry_run", message: "dry-run: target found by DocID search, delete skipped", page_index: 1 };
        rows.push(row);
        emit({ event: "duplicate.target.dry_run", ...row, master_id: deleteTarget.master_id, plantware_row: match.row });
        continue;
      }
      try {
        emit({ event: "duplicate.target.delete.started", doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, emp_code: deleteTarget.emp_code, page_index: 1, plantware_row: match.row, message: `Deleting DocID ${deleteTarget.doc_id}` });
        await deleteVisibleDocId(page, deleteTarget, (debugEvent) => emit({ event: "duplicate.delete.debug", doc_id: deleteTarget.doc_id, master_id: deleteTarget.master_id, page_index: 1, plantware_row: match.row, ...debugEvent, message: `Delete debug ${deleteTarget.doc_id}: ${String(debugEvent.step ?? "step")}` }));
        await gotoListPage(page);
        const stillVisible = await searchVisibleTargetByDocId(page, deleteTarget);
        if (stillVisible) {
          throw new Error(`DocID ${deleteTarget.doc_id} still visible after delete attempt`);
        }
        deletedRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: deleteTarget.doc_id, emp_code: deleteTarget.emp_code, doc_desc: deleteTarget.doc_desc, status: "deleted", message: "deleted and verified absent from list", page_index: 1 };
        rows.push(row);
        emit({ event: "duplicate.target.deleted", ...row, master_id: deleteTarget.master_id, plantware_row: match.row });
      } catch (error) {
        failedRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: deleteTarget.doc_id, emp_code: deleteTarget.emp_code, doc_desc: deleteTarget.doc_desc, status: "failed", message: error instanceof Error ? error.message : String(error), page_index: 1 };
        rows.push(row);
        emit({ event: "duplicate.target.failed", ...row, master_id: deleteTarget.master_id, plantware_row: match.row });
        await gotoListPage(page).catch(() => {});
      }
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
