import assert from "node:assert/strict";
import { taskRegisterSessionDivision, taskRegisterTargetLocCode } from "./delete-task-register-runner.js";
import type { DuplicateDocIdTarget, RunPayload } from "../types.js";

const baseTarget: DuplicateDocIdTarget = {
  master_id: "4834465",
  doc_id: "70897930_01",
  doc_date: "2026-05-08",
  emp_code: "",
  emp_name: "",
  doc_desc: "TASK REGISTER",
  amount: 201750,
  action: "DELETE_RECORD",
  keep_doc_id: "",
  category: "task_register",
  raw: { source: "task-register-pr-taskreg", loc_code: "dme" }
};

const payload = {
  division_code: "P1B",
  session_division_code: null
} as RunPayload;

assert.equal(taskRegisterTargetLocCode(baseTarget), "DME");
assert.equal(taskRegisterSessionDivision(payload, [baseTarget]), "DME");
assert.equal(taskRegisterSessionDivision({ ...payload, division_code: "AB1" } as RunPayload, [{ ...baseTarget, raw: {} }]), "AB1");
assert.throws(
  () => taskRegisterSessionDivision(payload, [baseTarget, { ...baseTarget, doc_id: "X_01", raw: { loc_code: "P2A" } }]),
  /one LocCode per run/
);
