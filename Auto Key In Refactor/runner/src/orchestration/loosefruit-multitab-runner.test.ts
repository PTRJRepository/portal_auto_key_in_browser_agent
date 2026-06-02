import assert from "node:assert/strict";
import { buildStagingComparisonUrl, filterLooseFruitRows, type StagingComparisonRow } from "../plantware/loosefruit-input.js";
import { estateSet, uniqueRowsByEmployee } from "./loosefruit-multitab-runner.js";

function row(extra: Partial<StagingComparisonRow>): StagingComparisonRow {
  return {
    emp_code: "A0001",
    emp_name: "Worker",
    gang: "A1H",
    gang_name: "Gang A1H",
    divisi: "A1",
    estate: "P1A",
    staging_brondol: 10,
    plantware_brondol: 4,
    selisih: 6,
    ...extra,
  };
}

assert.equal(
  buildStagingComparisonUrl("http://localhost:3001/upah/staging-comparison", "2026-05"),
  "http://localhost:8002/backend/upah/api/staging/staging-comparison?periode=2026-05",
);
assert.equal(
  buildStagingComparisonUrl("http://localhost:8002", "2026-05", "P1B"),
  "http://localhost:8002/backend/upah/api/staging/staging-comparison?periode=2026-05&division=P1B",
);

const rows = [
  row({ emp_code: "A0001", estate: "P1A", selisih: 2 }),
  row({ emp_code: "A0002", estate: "P1A", selisih: 0 }),
  row({ emp_code: "B0001", estate: "P1A", selisih: 5 }),
  row({ emp_code: "A0003", estate: "P1B", selisih: 4 }),
];
assert.deepEqual(filterLooseFruitRows(rows, "P1A").map(item => item.emp_code), ["A0001", "B0001"]);
assert.deepEqual(Array.from(estateSet(filterLooseFruitRows(rows))).sort(), ["P1A", "P1B"]);

const unique = uniqueRowsByEmployee([
  row({ emp_code: "A0001", selisih: 2 }),
  row({ emp_code: "A0001", selisih: 3 }),
  row({ emp_code: "A0002", selisih: 4 }),
]);
assert.deepEqual(unique.map(item => `${item.emp_code}:${item.selisih}`), ["A0001:2", "A0002:4"]);
