# Implementation Plan: Premi Remarks Sync Missing

## 1. Requirements Summary

Fix Manual Adjustment automation so premium-scope rows from `extend_db_ptrj.dbo.payroll_manual_adjustments` are fetched and filtered correctly.

Problem cases from user:
- Some premium search is too rigid, so `PREMI TIKET`, `PREMI TABUR PUPUK` / fertilizer transport variants, and other premium descriptions are not fetched or not selected.
- `KOREKSI PANEN` with `adjustment_type = POTONGAN_KOTOR` can be intentionally not input yet, but the app does not always treat it as input-needed.
- Rows already contain authoritative status in `remarks`, for example `... | sync:MISS | match:MISMATCH`. The app must read that directly.
- Only missing/different transactions should be input. Synced/matched rows must be skipped.

Canonical row example:

```json
{
  "adjustment_type": "POTONGAN_KOTOR",
  "adjustment_name": "KOREKSI PANEN",
  "amount": 88172,
  "remarks": "KOREKSI PANEN | (DE0004AB1) (DE) POTONGAN PREMI - (DE) POTONGAN PREMI | 88172 | sync:MISS | match:MISMATCH",
  "metadata_json": "{\"input_type\":\"blok\",\"items\":[{\"subblok\":\"P0815\",\"gang_code\":\"F2H\",\"jumlah\":88172}],\"total_amount\":88172}",
  "ad_code": "DE0004",
  "ad_code_desc": "(DE) POTONGAN PREMI",
  "task_desc": "(DE) POTONGAN PREMI"
}
```

Required behavior:
- Fetch all rows under manual premium scope from `payroll_manual_adjustments`, not only hard-coded premium names.
- Include `PREMI`, `POTONGAN_KOTOR`, and `POTONGAN_BERSIH` when user runs manual/premium preview where relevant.
- Prefer `adjustment_type` as the API scope. Do not require `adjustment_name` unless user explicitly filters one exact name.
- If `adjustment_type=PREMI` and `adjustment_name` is blank, fetch every premium row and every premium subtype. This includes all rows under the UI tab/category `premi` such as tiket, pupuk, pruning, raking, angkut, etc.
- If user types an `adjustment_name`, treat it as a narrow optional filter on top of `adjustment_type`.
- Classify premium-like entries by `adjustment_type`, `adjustment_name`, `ad_code_desc`, `task_desc`, and remarks ADCode description.
- Treat `remarks` tokens as source of truth for sync/match display and input eligibility.
- `sync:MISS`, `sync:MISSING`, `sync:NOT_FOUND` means missing.
- `match:MISMATCH`, `match:DIFF`, `match:PARTIAL`, or `sync:DIFF` means different.
- `sync:SYNC` and `match:MATCH` means already OK; skip input.
- Do not rely on `check-adtrans` or amount heuristics to override explicit remarks status.
- Preserve safe partial-premium behavior where a grouped parent has detail metadata and only some detail rows need input.

## 2. Evidence And Current Code Map

Current repo:
- `app/ui/main_window.py` already has `remarks_parts()`, `remarks_token()`, `sync_status_from_remarks()`, and `match_status_from_remarks()`.
- `app/ui/main_window.py` defines `PREMI_CATEGORY_KEYS = {"premi", "premi_tunjangan", "premi_tiket", "premi_hari_raya", "premi_kehadiran"}`.
- `app/ui/main_window.py` `records_requiring_fetch_verification()` only verifies non-synced premium categories or stale miss rows; this can miss non-premium `POTONGAN_KOTOR` rows with `match:MISMATCH`.
- `app/ui/main_window.py` `_record_is_mismatch()` only reads fetch verification status and does not directly read `match:` from remarks.
- `app/ui/main_window.py` premium retry-safe flow can skip mismatches because `build_premium_retry_plan_from_sync_status()` treats many sync-status rows as no retry unless ADTRANS partial logic applies.
- `app/ui/division_run_dialog.py` grouped premium fetch trigger only names `premi` and `premi_tunjangan`, but `query.requests_premium()` helps when `adjustment_type=PREMI`; category-specific launches for `premi_tiket` still need audit.
- `configs/adjustment-categories.json` has `premi_tiket`, `premi_hari_raya`, `premi_kehadiran`, and generic `premi`, but no explicit fertilizer/tabur pupuk tokens.
- `app/core/api_client.py` `ManualAdjustmentQuery.with_grouped_premium_details()` forces `adjustment_type=PREMI`, `view=grouped`, `metadata_only=true`.
- `app/core/api_client.py` `_normalize_grouped_premium_records()` flattens grouped `premium_transactions`/metadata into runner rows.
- `app/core/models.py` `metadata_detail_items()` supports `metadata_json`, `items`, `detail_items`, `blok_items`, and `kendaraan_items`.
- `runner/src/plantware/page-actions.ts` picks premium detail behavior from `detail_type`, `subblok`, `vehicle_code`, and category strategy.

Reference project:
- `backend/src/utils/manualAdjustmentRemarkParser.ts` documents remarks format and parses `sync:`/`match:` tokens.
- `backend/src/services/manualAdjustmentService.ts` has `DETAIL_TOTAL_SYNC_PREMI_NAMES = new Set(["PREMI PRUNING", "PREMI RAKING", "PREMI TIKET"])`.
- `backend/src/services/manualAdjustmentService.ts` normalizes `POTONGAN_KOTOR` to `KOREKSI ...` and maps it to `DE0004` / `(DE) POTONGAN PREMI`.
- `backend/data/premium_definitions.json` includes `PREMI TIKET`, `PREMI ANGKUT PUPUK`, and many other premium definitions. It is a better source than local hard-coded contains lists.

External backend edit is allowed if the endpoint is the blocker:
- Path: `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production`.
- Main endpoint: `backend/src/api/payroll.ts` route `/payroll/manual-adjustment/by-api-key`.
- Main service: `backend/src/services/manualAdjustmentService.ts` manual adjustment fetch/grouping logic.
- Remarks helper: `backend/src/utils/manualAdjustmentRemarkParser.ts`.
- Rule: fix endpoint to return all rows for requested `adjustment_type` values first; desktop app should not compensate for missing API rows with brittle name lists.

Status source from refactor UI:
- `frontend/src/pages/AggregationSeederPage.jsx` button `Update Sync Status Manual Adj` calls `/payroll/manual-adjustment/sync-status/by-api-key` for `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, and `AUTO_BUFFER`.
- That status updater writes/updates `remarks` tokens after checking PR_ADTRANS/PR_ADTRANS_ARC totals.
- UI/log rule there is `SYNC` = OK/green/success, `DIFF` = amount exists but differs, `MISS` = non-zero target has no matching ADTRANS.
- Auto Key In must consume the same status contract: `SYNC/MATCH` skip, `MISS/DIFF/MISMATCH/PARTIAL` input-needed.
- `backend/src/services/manualAdjustmentService.ts` compare/sync status sets `sync:MISS` when no ADTRANS exists and `match:MISMATCH` when amount/status differs.

## 3. Architecture Decisions

Create a small remarks-status domain helper in Python instead of scattering token checks in UI methods. Current global functions in `main_window.py` can be moved or wrapped by a testable helper in `app/core/manual_adjustment_status.py`.

Keep explicit remarks status authoritative. If `remarks` has `sync:` or `match:`, UI filtering must use those tokens before calling sync-status/check-adtrans. Sync-status endpoint can still be used after successful input to update rows to `SYNC`, but it must not hide user-visible `MISS`/`MISMATCH` rows before input.

Broaden manual-scope fetching in the UI. Premium preview can still use grouped `PREMI` endpoint for detail-rich premium rows, but missing/diff manual adjustment selection must also include `POTONGAN_KOTOR` rows like `KOREKSI PANEN`. If the user chooses a single category, preserve category focus; if the user chooses manual/premium retry, fetch all applicable manual types.

Normalize category detection through one rule set. Local `CategoryRegistry.detect()` should include description/task/remarks-based fallback or a helper should pass a combined name string. Fertilizer/tabur/pupuk variants should land in generic `premi` unless there is a more specific category. `KOREKSI PANEN` should land in `potongan_upah_kotor`/`koreksi`, not be dropped.

Do not change Plantware UI runner semantics until input data is verified. First make fetched rows correct and tested. Then add runner tests only if amount-only or blok/kendaraan details reveal bad behavior.

## 4. Task Breakdown

### IMPL-1: Centralize Remarks Status Rules

Owns status parser and unit tests.

Files:
- `app/core/manual_adjustment_status.py` (new)
- `app/ui/main_window.py`
- `tests/test_manual_adjustment_status.py` (new)

Actions:
- Add parser for pipe-delimited remarks matching reference format: `ADJUSTMENT_NAME | AD_CODE - DESC | AMOUNT | sync:STATUS | match:STATUS`.
- Expose functions like `remarks_sync_status()`, `remarks_match_status()`, `is_sync_ok()`, `is_missing_from_remarks()`, `is_mismatch_from_remarks()`, and `input_needed_from_remarks()`.
- Treat `MISS`, `MISSING`, `NOT_FOUND` as missing.
- Treat `MISMATCH`, `DIFF`, `PARTIAL` as mismatch/diff.
- Treat explicit tokens as authoritative over parsed amount fallback.
- Keep existing fallback behavior for old remarks without tokens: parse third segment amount; otherwise `MANUAL` or `NO REMARKS`.
- Update `main_window.py` global functions to delegate to helper to preserve call sites.

Convergence:
- Example `KOREKSI PANEN | ... | sync:MISS | match:MISMATCH` returns `sync=MISS`, `match=MISMATCH`, `input_needed=True`.
- `sync:SYNC | match:MATCH` returns `input_needed=False`.
- `sync:DIFF | match:MISMATCH` returns `input_needed=True`.
- Empty/no-pipe remarks keep current labels.

### IMPL-2: Broaden Manual Category Fetch And Classification

Owns fetched rows, category detection, and endpoint changes if the API filters too narrowly.

Files:
- `configs/adjustment-categories.json`
- `app/core/category_registry.py`
- `app/core/api_client.py`
- `app/ui/division_run_dialog.py`
- `tests/test_api_models.py`
- `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production\backend\src\api\payroll.ts` (external, if needed)
- `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production\backend\src\services\manualAdjustmentService.ts` (external, if needed)
- `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production\backend\src\api\payroll.manualAdjustmentByApiKey.test.ts` (external, if needed)

Actions:
- Add match tokens for fertilizer/tabur/pupuk premium variants, e.g. `TABUR PUPUK`, `ANGKUT PUPUK`, `PUPUK`, while preserving generic `PREMI` fallback.
- Audit backend `/by-api-key` behavior: with `adjustment_type=PREMI` it must return all premium names; with `adjustment_type=POTONGAN_KOTOR` it must return all koreksi rows, including `KOREKSI PANEN`.
- If backend currently requires exact `adjustment_name` or rigid premium definition match, relax it to adjustment-type scope and add tests there.
- Make category detection consider `adjustment_name`, `ad_code_desc`, `description`, `task_desc`, and remarks ADCode description where available.
- Ensure grouped premium fetch is triggered for every `PREMI_CATEGORY_KEYS` category, not only `premi` and `premi_tunjangan`.
- Add a manual-scope query path for mixed missing/diff preview that can fetch `PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH` when user wants all missing manual entries.
- Preserve division alias behavior (`P1A -> PG1A`, etc.) for manual types.
- Ensure `metadata_json` and `detail_items` survive normalization for `POTONGAN_KOTOR` rows like `KOREKSI PANEN`.

Convergence:
- `PREMI TIKET` normalizes as `premi_tiket` or generic `premi` and remains runnable.
- `PREMI ANGKUT PUPUK` / tabur pupuk variant normalizes as premium-scope and remains runnable.
- `KOREKSI PANEN` with `POTONGAN_KOTOR` normalizes as `potongan_upah_kotor`/`koreksi` and remains visible when remarks say input is needed.
- Category-specific Division Run for `premi_tiket` still uses grouped metadata fetch.
- External endpoint test proves `adjustment_type=PREMI` returns mixed `adjustment_name` rows without passing `adjustment_name`.
- External endpoint test proves `adjustment_type=POTONGAN_KOTOR` returns `KOREKSI PANEN` without passing `adjustment_name`.

### IMPL-3: Filter Runs From Remarks, Not Verification Guessing

Owns preview/run eligibility.

Files:
- `app/ui/main_window.py`
- `tests/test_api_models.py` or new UI-free tests for filter helpers

Actions:
- Update `_record_is_miss()` to return true from remarks `sync:MISS/MISSING/NOT_FOUND` even without fetch verification.
- Update `_record_is_mismatch()` to return true from remarks `match:MISMATCH/DIFF/PARTIAL` and `sync:DIFF/PARTIAL`.
- Update `records_requiring_fetch_verification()` so explicit remarks input-needed rows do not depend on category being in `PREMI_CATEGORY_KEYS`.
- Change premium retry-safe filter text/logic so `MISMATCH` rows are not skipped if user selected missing+mismatch processing.
- Ensure `build_premium_retry_plan_from_sync_status()` only refines ambiguous grouped premium partials; it must not remove rows already explicit `sync:MISS`/`match:MISMATCH` from remarks.
- When `process_mismatch_missing_only` is enabled, keep rows where helper says `input_needed_from_remarks()`.
- When `process_only_miss` is enabled, keep only helper `is_missing_from_remarks()` unless mismatch option is also enabled.
- In table display, show `API Sync = MISS` and `API Match = MISMATCH` directly from remarks for the user example.

Convergence:
- User example row appears as pending input, not already-in-DB/not-checked.
- Synced rows with `sync:SYNC | match:MATCH` are filtered out from run payload.
- Diff rows with `sync:DIFF | match:MISMATCH` are included when mismatch/missing mode is active.
- Non-premium manual rows with `POTONGAN_KOTOR` and explicit missing/mismatch status are included when manual missing/diff scope is active.

### IMPL-4: Runner Compatibility And Regression Tests

Owns runner edge cases and final verification.

Files:
- `runner/src/plantware/page-actions.ts`
- `runner/src/plantware/page-actions.test.ts`
- `runner/src/orchestration/row-assignment.test.ts`
- `tests/test_api_models.py`
- `tests/test_manual_adjustment_status.py`

Actions:
- Add runner tests for amount-only premium (`PREMI TIKET`) so it does not require blok/kendaraan fields.
- Add runner tests for blok-based `KOREKSI PANEN`/potongan row if current category strategy routes it differently than premium details.
- Verify `premiumDetailGroupKey()` groups only detail rows that should continue on same Plantware detail page.
- Add Python tests for grouped premium normalization containing `metadata_json` `items` with `subblok`, `gang_code`, and `jumlah`.
- Add regression fixture using user sample remarks and metadata.
- Run focused tests first, then broader Python and runner tests if available.

Convergence:
- `pytest tests/test_manual_adjustment_status.py tests/test_api_models.py` passes.
- Runner unit tests for premium amount-only and detail grouping pass.
- Manual preview/run payload contains only input-needed rows for mixed `SYNC`, `MISS`, and `MISMATCH` fixtures.

## 5. Validation Plan

Focused validation:
- `pytest tests/test_manual_adjustment_status.py`
- `pytest tests/test_api_models.py`
- `cd runner; npm test -- page-actions row-assignment` or project-equivalent runner test command.

Manual validation:
- Fetch period `5/2026`, estate/division containing employee `F0499`.
- Confirm row `KOREKSI PANEN`, amount `88172`, remarks `sync:MISS | match:MISMATCH` is visible and marked pending.
- Confirm `PREMI TIKET` and fertilizer/pupuk premium rows are visible when present in `extend_db_ptrj`.
- Confirm run preview excludes rows with `sync:SYNC | match:MATCH`.
- Confirm run preview includes only `MISS`/`MISMATCH` rows when mismatch/missing filter active.

## 6. Open Questions

- Exact local name for `PREMI TABUR PUPUK` may differ in `payroll_manual_adjustments`; implementation should match `PUPUK`/AD description broadly but safely.
- If backend `/by-api-key` grouped view only returns `PREMI`, current app may need a second flat query for `POTONGAN_KOTOR`/`POTONGAN_BERSIH` and merge results.
- If `sync-status/by-api-key` overwrites `MISS` with `SKIPPED` for no ADTRANS, UI must preserve explicit remarks status before verification.
