import assert from "node:assert/strict";
import { isBrowserClosedError } from "./multi-tab-runner.js";

assert.equal(isBrowserClosedError(new Error("page.waitForTimeout: Target page, context or browser has been closed")), true);
assert.equal(isBrowserClosedError(new Error("Target closed")), true);
assert.equal(isBrowserClosedError(new Error("PREMI detail row for G0352 / PREMI JAGA is missing ad_code")), false);
assert.equal(isBrowserClosedError(new Error("Add not confirmed for G0352 / (AL) TUNJANGAN PREMI ((PM) PRUNING)")), false);
assert.equal(isBrowserClosedError("Validation error after Add: Please select Employee"), false);
