import assert from "node:assert/strict";
import type { Page } from "playwright";
import { isTaskRegisterTarget, searchTaskRegisterDocId } from "./task-register-duplicates.js";
import type { DuplicateDocIdTarget } from "../types.js";

const target: DuplicateDocIdTarget = {
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
  raw: { source: "task-register-pr-taskreg", loc_code: "DME" }
};

const calls: string[] = [];

const page = {
  locator(selector: string) {
    if (selector === "#MainContent_txtSrchDocID") {
      return {
        fill: async (value: string) => calls.push(`fill:${value}`),
        press: async (key: string) => calls.push(`press:${key}`)
      };
    }
    if (selector === "#MainContent_btnSearch") {
      return {
        first() {
          return {
            isVisible: async () => true,
            click: async () => calls.push("click:search")
          };
        }
      };
    }
    if (selector === "#MainContent_gvList, #MainContent_txtSrchDocID") {
      return {
        first() {
          return { waitFor: async () => calls.push("wait:list") };
        }
      };
    }
    if (selector === "#MainContent_gvList") {
      return { textContent: async () => "4834465 70897930_01 DME 201750.00000" };
    }
    if (selector === "#MainContent_gvList_lbDelete_0") {
      return { isVisible: async () => true };
    }
    return {
      first() {
        return { isVisible: async () => false };
      }
    };
  },
  waitForLoadState: async () => calls.push("wait:dom"),
  url: () => "http://plantwarep3:8001/en/PR/trx/frmPrTrxTaskRegisterList.aspx"
} as unknown as Page;

const match = await searchTaskRegisterDocId(page, target);

assert.deepEqual(calls, [
  "fill:70897930_01",
  "wait:dom",
  "click:search",
  "wait:list"
]);
assert.equal(match?.docId, "70897930_01");
assert.equal(match?.deleteVisible, true);
assert.equal(isTaskRegisterTarget(target), true);
assert.equal(isTaskRegisterTarget({ ...target, category: "premi", raw: { source: "compare-adtrans" } }), false);
