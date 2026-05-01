import assert from "node:assert/strict";
import { deleteDocIdActionSupported, duplicateCleanupCategorySupported, targetWithMatchedMasterId } from "./delete-duplicates-runner.js";

assert.equal(duplicateCleanupCategorySupported("spsi"), true);
assert.equal(duplicateCleanupCategorySupported("masa_kerja"), true);
assert.equal(duplicateCleanupCategorySupported("tunjangan_jabatan"), true);
assert.equal(duplicateCleanupCategorySupported("premi"), true);
assert.equal(duplicateCleanupCategorySupported("premi_tunjangan"), true);
assert.equal(duplicateCleanupCategorySupported("potongan_upah_kotor"), true);
assert.equal(duplicateCleanupCategorySupported("koreksi"), true);
assert.equal(duplicateCleanupCategorySupported("potongan_upah_bersih"), true);
assert.equal(duplicateCleanupCategorySupported("unknown"), false);

assert.equal(deleteDocIdActionSupported("DELETE_OLD"), true);
assert.equal(deleteDocIdActionSupported("DELETE_RECORD"), true);
assert.equal(deleteDocIdActionSupported("KEEP_NEWEST"), false);

assert.deepEqual(
  targetWithMatchedMasterId(
    {
      master_id: "",
      doc_id: "ADAB226044536",
      doc_date: "",
      emp_code: "",
      emp_name: "",
      doc_desc: "jabatan",
      action: "DELETE_RECORD",
      keep_doc_id: "",
      category: "tunjangan_jabatan"
    },
    { docId: "ADAB226044536", masterId: "677711", empCode: "H0033", docDesc: "TUNJANGAN JABATAN" }
  ).master_id,
  "677711"
);
