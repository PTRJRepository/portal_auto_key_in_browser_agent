import type { DeleteDuplicateRowResult, DuplicateDocIdTarget, RunPayload, RunResult } from "../types.js";
import { BrowserSession } from "../session/browser-session.js";
import { sessionDivisionCode } from "../payload.js";
import { deleteTaskRegisterDocId, gotoTaskRegisterListPage, searchTaskRegisterDocId } from "../plantware/task-register-duplicates.js";

type Emit = (event: Record<string, unknown>) => void;

export function taskRegisterTargetLocCode(target: DuplicateDocIdTarget): string {
  const raw = target.raw ?? {};
  return String(raw.loc_code ?? raw.locCode ?? raw.LocCode ?? "").trim().toUpperCase();
}

export function taskRegisterSessionDivision(payload: RunPayload, targets: DuplicateDocIdTarget[]): string {
  const locCodes = [...new Set(targets.map(taskRegisterTargetLocCode).filter(Boolean))];
  if (locCodes.length > 1) {
    throw new Error(`Task Register cleanup requires one LocCode per run. Found: ${locCodes.join(", ")}`);
  }
  return locCodes[0] || sessionDivisionCode(payload);
}

export async function runDeleteTaskRegisterDuplicates(payload: RunPayload, emit: Emit, inputTargets?: DuplicateDocIdTarget[]): Promise<RunResult> {
  const started = new Date().toISOString();
  const dryRun = payload.delete_dry_run ?? true;
  const targets = (inputTargets ?? payload.duplicate_targets ?? []).filter((target) => String(target.action ?? "").trim().toUpperCase() === "DELETE_RECORD" && target.doc_id);
  const rows: DeleteDuplicateRowResult[] = [];
  let deletedRows = 0;
  let dryRunRows = 0;
  let notFoundRows = 0;
  let failedRows = 0;
  const sessionDivision = taskRegisterSessionDivision(payload, targets);

  emit({ event: "task_register.run.started", total_targets: targets.length, dry_run: dryRun, loc_code: sessionDivision, message: `Task Register duplicate cleanup started for ${targets.length} targets at ${sessionDivision}` });

  const session = new BrowserSession({
    headless: payload.headless,
    freshLoginFirst: false,
    loginFallback: false,
    division: sessionDivision
  });

  try {
    await session.start();
    emit({ event: "session.ready", division_code: payload.division_code, session_division_code: sessionDivision, reused: session.sessionReused, session_path: session.getSessionPath(), message: session.sessionReused ? "Session reused" : "Fresh session login completed" });
    const page = await session.newPage();
    await gotoTaskRegisterListPage(page);

    for (const target of targets) {
      const locCode = taskRegisterTargetLocCode(target) || sessionDivision;
      emit({ event: "task_register.search.started", doc_id: target.doc_id, loc_code: locCode, message: `Searching Task Register DocID ${target.doc_id}` });
      const match = await searchTaskRegisterDocId(page, target);
      if (!match) {
        notFoundRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, doc_desc: target.doc_desc, status: "not_found", message: "Task Register DocID not found after search", page_index: 1 };
        rows.push(row);
        emit({ event: "task_register.target.not_found", ...row, loc_code: locCode });
        continue;
      }

      emit({ event: "task_register.target.matched", doc_id: target.doc_id, loc_code: locCode, plantware_row: match, message: `Matched Task Register DocID ${target.doc_id}` });
      if (dryRun) {
        dryRunRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, doc_desc: target.doc_desc, status: "dry_run", message: "dry-run: Task Register target found, delete skipped", page_index: 1 };
        rows.push(row);
        emit({ event: "task_register.target.dry_run", ...row, loc_code: locCode, plantware_row: match });
        continue;
      }

      try {
        emit({ event: "task_register.target.delete.started", doc_id: target.doc_id, loc_code: locCode, message: `Deleting Task Register DocID ${target.doc_id}` });
        await deleteTaskRegisterDocId(page, target, (debugEvent) => emit({ event: "task_register.delete.debug", doc_id: target.doc_id, loc_code: locCode, ...debugEvent, message: `Task Register delete debug ${target.doc_id}: ${String(debugEvent.step ?? "step")}` }));
        await gotoTaskRegisterListPage(page);
        const stillVisible = await searchTaskRegisterDocId(page, target);
        if (stillVisible) {
          throw new Error(`Task Register DocID ${target.doc_id} still visible after delete attempt`);
        }
        deletedRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, doc_desc: target.doc_desc, status: "deleted", message: "deleted and verified absent from Task Register list", page_index: 1 };
        rows.push(row);
        emit({ event: "task_register.target.deleted", ...row, loc_code: locCode });
      } catch (error) {
        failedRows += 1;
        const row: DeleteDuplicateRowResult = { doc_id: target.doc_id, doc_desc: target.doc_desc, status: "failed", message: error instanceof Error ? error.message : String(error), page_index: 1 };
        rows.push(row);
        emit({ event: "task_register.target.failed", ...row, loc_code: locCode });
        await gotoTaskRegisterListPage(page).catch(() => {});
      }
    }

    emit({ event: "task_register.run.completed", deleted_rows: deletedRows, dry_run_rows: dryRunRows, not_found_rows: notFoundRows, failed_rows: failedRows, message: `Task Register cleanup completed: deleted=${deletedRows}, dry_run=${dryRunRows}, not_found=${notFoundRows}, failed=${failedRows}` });

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
      error_summary: failedRows ? `${failedRows} Task Register deletes failed` : null,
      rows
    };
  } finally {
    await session.close();
  }
}
