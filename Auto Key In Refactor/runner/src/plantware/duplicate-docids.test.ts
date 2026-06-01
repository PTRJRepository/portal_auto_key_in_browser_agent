import assert from "node:assert/strict";
import type { Page } from "playwright";
import { searchVisibleTargetByDocId } from "./duplicate-docids.js";
import type { DuplicateDocIdTarget } from "../types.js";

const calls: string[] = [];
const target: DuplicateDocIdTarget = {
  master_id: "",
  doc_id: "ADIJL26041001",
  doc_date: "",
  emp_code: "",
  emp_name: "",
  doc_desc: "PREMI TBS",
  action: "DELETE_RECORD",
  keep_doc_id: "",
  category: "premi"
};

const page = {
  locator(selector: string) {
    if (selector === "#MainContent_txtDocID") {
      return {
        isVisible: async () => true,
        fill: async (value: string) => calls.push(`fill:${value}`)
      };
    }
    if (selector === "#MainContent_btnSearch") {
      return {
        click: async () => calls.push("click:search")
      };
    }
    if (selector === "#MainContent_gvLine tr") {
      return {
        evaluateAll: async () => [{
          docId: "ADIJL26041001",
          masterId: "677001",
          empCode: "L0073",
          docDesc: "PREMI TBS"
        }]
      };
    }
    if (selector === "#MainContent_gvLine, a[href*='frmPrTrxADDets.aspx?MasterID=']") {
      return {
        first() {
          return { waitFor: async () => calls.push("wait:list") };
        }
      };
    }
    throw new Error(`Unexpected selector ${selector}`);
  },
  waitForLoadState: async () => calls.push("wait:dom"),
  url: () => "https://plantware.example/frmPrTrxADLists.aspx"
} as unknown as Page;

const match = await searchVisibleTargetByDocId(page, target);

assert.equal(match?.row.docId, "ADIJL26041001");
assert.deepEqual(calls, [
  "fill:ADIJL26041001",
  "wait:dom",
  "click:search",
  "wait:list"
]);
