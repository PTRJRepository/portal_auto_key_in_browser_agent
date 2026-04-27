import { BrowserSession } from "../session/browser-session.js";
import type { RunPayload, RunResult } from "../types.js";
import type { EmitEvent } from "./mock-runner.js";

export async function runGetSession(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const session = new BrowserSession({ headless: payload.headless, freshLoginFirst: true, division: payload.division_code });
  emit({ event: "session.get.started", message: "Getting fresh Plantware session..." });
  try {
    await session.start();
    emit({ event: "session.get.completed", message: "Fresh session saved and ready; no records attempted", division_code: payload.division_code, session_path: session.getSessionPath(), session_reused: false, attempted_rows: 0, inserted_rows: 0 });
    return sessionResult(payload, started_at, true, false, null);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emit({ event: "session.get.failed", message });
    return sessionResult(payload, started_at, false, false, message);
  } finally {
    await session.close();
  }
}

export async function runTestSession(payload: RunPayload, emit: EmitEvent): Promise<RunResult> {
  const started_at = new Date().toISOString();
  const session = new BrowserSession({ headless: payload.headless, freshLoginFirst: false, division: payload.division_code });
  emit({ event: "session.test.started", message: "Testing saved Plantware session..." });
  try {
    await session.start();
    emit({ event: "session.test.completed", message: session.sessionReused ? "Saved session is valid; no records attempted" : "Saved session was missing/invalid; fresh session created; no records attempted", division_code: payload.division_code, session_path: session.getSessionPath(), session_reused: session.sessionReused, attempted_rows: 0, inserted_rows: 0 });
    return sessionResult(payload, started_at, true, session.sessionReused, null);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emit({ event: "session.test.failed", message });
    return sessionResult(payload, started_at, false, false, message);
  } finally {
    await session.close();
  }
}

function sessionResult(
  payload: RunPayload,
  started_at: string,
  success: boolean,
  session_reused: boolean,
  error_summary: string | null
): RunResult {
  return {
    success,
    started_at,
    finished_at: new Date().toISOString(),
    runner_mode: payload.runner_mode,
    session_reused,
    total_records: 0,
    attempted_rows: 0,
    inserted_rows: 0,
    skipped_existing_rows: 0,
    failed_rows: success ? 0 : 1,
    error_summary,
    rows: []
  };
}
