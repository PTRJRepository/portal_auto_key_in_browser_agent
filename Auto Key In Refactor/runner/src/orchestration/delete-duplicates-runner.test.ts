import assert from "node:assert/strict";
import { duplicateCleanupCategorySupported } from "./delete-duplicates-runner.js";

assert.equal(duplicateCleanupCategorySupported("spsi"), true);
assert.equal(duplicateCleanupCategorySupported("masa_kerja"), true);
assert.equal(duplicateCleanupCategorySupported("tunjangan_jabatan"), true);
assert.equal(duplicateCleanupCategorySupported("premi"), true);
assert.equal(duplicateCleanupCategorySupported("premi_tunjangan"), true);
assert.equal(duplicateCleanupCategorySupported("potongan_upah_kotor"), true);
assert.equal(duplicateCleanupCategorySupported("koreksi"), true);
assert.equal(duplicateCleanupCategorySupported("potongan_upah_bersih"), true);
assert.equal(duplicateCleanupCategorySupported("unknown"), false);
