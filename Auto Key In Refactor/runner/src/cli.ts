import * as fs from "node:fs";
import type { RunPayload, RunResult } from "./types.js";
import { runDryRun } from "./orchestration/dry-runner.js";
import { runMock } from "./orchestration/mock-runner.js";
import { runMultiTabSharedSession } from "./orchestration/multi-tab-runner.js";
import { runGetSession, runTestSession } from "./orchestration/session-runner.js";
import { runDeleteDuplicates } from "./orchestration/delete-duplicates-runner.js";
import { runDebugDuplicateScan } from "./orchestration/debug-duplicate-scan-runner.js";

function emit(event: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

function parsePayloadPath(): string {
  const index = process.argv.indexOf("--payload");
  if (index === -1 || !process.argv[index + 1]) {
    throw new Error("Missing --payload <path>");
  }
  return process.argv[index + 1];
}

async function main(): Promise<void> {
  const payloadPath = parsePayloadPath();
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf-8")) as RunPayload;
  let result: RunResult;
  if (payload.operation === "debug_duplicate_scan") {
    result = await runDebugDuplicateScan(payload, emit);
  } else if (payload.operation === "delete_duplicates") {
    result = await runDeleteDuplicates(payload, emit);
  } else if (payload.runner_mode === "mock") {
    result = await runMock(payload, emit);
  } else if (payload.runner_mode === "dry_run") {
    result = await runDryRun(payload, emit);
  } else if (payload.runner_mode === "get_session") {
    result = await runGetSession(payload, emit);
  } else if (payload.runner_mode === "test_session") {
    result = await runTestSession(payload, emit);
  } else {
    result = await runMultiTabSharedSession(payload, emit);
  }
  emit({ event: "result", result });
  process.exit(result.success ? 0 : 1);
}

main().catch((error) => {
  emit({ event: "run.failed", message: error instanceof Error ? error.message : String(error) });
  process.exit(1);
});
