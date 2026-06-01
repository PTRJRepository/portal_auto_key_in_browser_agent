# Implementation Plan: Loosefruit Duplicate Cleanup

## 1. Requirements Summary

Add a feature in the desktop app to find and delete duplicate Loosefruit transactions from `db_ptrj.dbo.PR_LOOSEFRUIT`. The target records are rows whose `DocID` contains a literal underscore, matching the user query:

```sql
SELECT TOP (1000)
    [ID], [DocID], [DocDate], [DocDesc], [LocCode], [AccMonth], [AccYear],
    [PhyMonth], [PhyYear], [Status], [CreatedBy], [CreatedDate],
    [UpdatedBy], [UpdatedDate], [ImpFlag], [AutoCalMT], [TotalMT]
FROM [db_ptrj].[dbo].[PR_LOOSEFRUIT]
WHERE [DocID] LIKE '%[_]%'
ORDER BY [DocID];
```

Required behavior:
- Fetch duplicate Loosefruit targets from Query Gateway.
- Empty LocCode means all locations.
- Render targets in the Duplicate Cleanup tab with clearer layout.
- Default to dry-run scan.
- Actual delete must require confirmation.
- Delete through existing Plantware browser flow, not raw SQL DELETE, unless separately approved.
- Support all selected LocCodes safely.

## 2. Architecture Decisions

Use Query Gateway only for target discovery. The app already has `PlantwareDbPtrjGateway.fetch_all()` and Task Register duplicate query patterns. Loosefruit should use the same repository style and parameterized SQL with `DocID LIKE @docIdPattern` and `@docIdPattern = '%[_]%'`.

Use existing browser deletion for actual removal. `runner/src/orchestration/delete-loosefruit-runner.ts` already routes through Plantware UI, validates detail page, clicks Delete, and verifies the row is absent. This avoids bypassing Plantware side effects.

Support all-location cleanup by grouping selected Loosefruit targets by `LocCode`. Current runner throws when more than one LocCode is present. Update it to process groups sequentially, one `BrowserSession` per LocCode, while keeping saved-session safety (`loginFallback=false`). UI should also preflight missing session files and show which LocCodes need Get Session.

Keep a single duplicate target table unless implementation discovers UI constraints. Current Task Register flow already reuses `duplicate_table` with `DuplicateDocIdTarget`; Loosefruit can render `LocCode` in the `Emp/Loc` column and `LOOSEFRUIT` in `DocDesc`. Layout polish should focus on clearer grouped controls, status copy, and scroll behavior.

## 3. Task Breakdown

### IMPL-1: Stabilize Loosefruit Gateway And Mapping

Owns Python data access and model conversion.

Files:
- `app/core/loosefruit_gateway.py`
- `app/core/task_register_gateway.py`
- `tests/test_task_register_gateway.py` or new `tests/test_loosefruit_gateway.py`

Actions:
- Resolve duplicate/incomplete Loosefruit repository ownership.
- Prefer a complete dedicated `app/core/loosefruit_gateway.py` and import it from UI.
- Keep compatibility if existing code imports Loosefruit objects from `task_register_gateway.py`.
- Implement `list_duplicate_doc_ids()` and `list_duplicate_targets()` with optional `loc_code`, `acc_month`, `acc_year`, and `limit`.
- Use `SELECT TOP ({limit})` with the exact column set from the user query.
- Use `WHERE [DocID] LIKE @docIdPattern` and params `{"docIdPattern": "%[_]%"}`.
- If `loc_code` is blank, do not add a LocCode predicate.
- Map `ID` to `master_id`, `TotalMT` to `amount`, `DocDesc` default to `LOOSEFRUIT`, category `loosefruit`, source `loosefruit-pr-loosefruit`, action `DELETE_RECORD`.

Convergence:
- Python import of Loosefruit gateway works.
- Query clamps limit to 1..10000.
- SQL contains `FROM [dbo].[PR_LOOSEFRUIT]`, `SELECT TOP (...)`, and literal-underscore LIKE pattern.
- All-location query has no `[LocCode] = @locCode` predicate.

### IMPL-2: Support All-Location Loosefruit Runner

Owns TypeScript runner behavior.

Files:
- `runner/src/orchestration/delete-loosefruit-runner.ts`
- `runner/src/plantware/loosefruit-page.ts`
- `runner/src/types.ts`
- `runner/src/orchestration/delete-loosefruit-runner.test.ts`

Actions:
- Keep `operation: "delete_loosefruit"` because `runner/src/cli.ts` already routes it.
- Add/export a helper that groups Loosefruit targets by normalized LocCode.
- Replace the current single-LocCode rejection with sequential per-LocCode processing.
- For each LocCode group, start `BrowserSession({ division: locCode, freshLoginFirst: false, loginFallback: false })`.
- Emit `loosefruit.group.started`, `session.ready`, per-target events, `loosefruit.group.completed`, and final aggregate `loosefruit.run.completed`.
- Preserve dry-run behavior and post-delete verification.
- If a LocCode is missing from a target, fall back to payload session division or division code; if still missing, fail that target clearly.

Convergence:
- Single-location behavior remains unchanged.
- Multi-location payload no longer throws before processing.
- Aggregated result counts include deleted, dry_run, not_found, failed across all groups.
- Failed group does not erase results already collected for other groups.

### IMPL-3: Add Proper UI Layout And Loosefruit Flow

Owns PySide UI and RunPayload construction.

Files:
- `app/ui/main_window.py`
- `tests/test_api_models.py`

Actions:
- Import Loosefruit repository from the stabilized module.
- Add `LoosefruitFetchWorker` using the same QObject/QThread pattern as `TaskRegisterFetchWorker`.
- Improve Duplicate Cleanup tab layout so three cleanup sources are visually clear:
  - Existing ADTRANS duplicate cleanup group.
  - Existing Task Register duplicate DocID group.
  - New Loosefruit duplicate DocID group.
- Use a compact grid or scrollable control area so controls do not crowd the table.
- New Loosefruit controls:
  - AccMonth spinbox, 0 means all or default to current period depending on implementation decision.
  - AccYear spinbox, 0 means all or default to current period depending on implementation decision.
  - LocCode text field, blank means all locations.
  - Limit spinbox default 1000.
  - Dry run checkbox checked by default.
  - Fetch button.
  - Scan/Delete selected button.
  - Status label that reports count and LocCode coverage.
- On fetch complete, set `self.duplicate_targets` to Loosefruit targets and call `_render_duplicate_targets()`.
- Add `_targets_are_loosefruit()` helper.
- Extend `_duplicate_category_supported()`, `_duplicate_run_period()`, `_duplicate_run_division_code()` or equivalent so Loosefruit does not get blocked by ADTRANS category rules.
- Before run, collect selected Loosefruit LocCodes and validate saved session availability for all of them. Show missing LocCodes in one warning.
- Build `RunPayload(operation="delete_loosefruit", category_key="loosefruit", duplicate_targets=selected, delete_dry_run=dry_run)`.
- Extend `_handle_runner_event()` to route `loosefruit.*` events into `_handle_duplicate_event()` and run log table.
- Ensure `_set_run_buttons_enabled()` covers new fetch/delete buttons.
- Sync default LocCode when Config division changes, without forcing all-location field if user intentionally left it blank.

Convergence:
- Duplicate Cleanup tab has a clearer layout with Loosefruit controls visible.
- Fetch all locations returns and renders targets from multiple LocCodes.
- Dry run starts `delete_loosefruit` and updates row statuses.
- Actual delete asks for confirmation and includes selected count plus LocCode count.
- Missing sessions block before runner starts, with actionable LocCode list.

### IMPL-4: Tests, Docs, Verification

Owns coverage and docs.

Files:
- `tests/test_task_register_gateway.py` or `tests/test_loosefruit_gateway.py`
- `tests/test_api_models.py`
- `runner/src/orchestration/delete-loosefruit-runner.test.ts`
- `README.md`

Actions:
- Add gateway tests for SQL, params, limit clamp, all-location behavior, row-to-target mapping.
- Add UI tests for fetch worker, fetch completion rendering, payload construction, operation `delete_loosefruit`, dry-run default, multi-LocCode session validation, and `loosefruit.*` event updates.
- Add runner tests for LocCode grouping and category/source detection.
- Update README Duplicate Cleanup section with Loosefruit workflow, all-location scan behavior, dry-run safety, and Get Session requirement per LocCode.
- Run focused Python and TypeScript tests.

Convergence:
- Python tests pass for new and affected UI/gateway behavior.
- Runner tests pass.
- Runner build passes from `runner` package.
- README explains how to use the feature.

## 4. Implementation Strategy

Recommended execution: sequential.

1. Fix data access first because UI depends on stable target objects.
2. Fix runner all-location support next because UI payload behavior depends on it.
3. Add UI layout and wiring once contracts are stable.
4. Add docs and run focused verification.

Do not direct-edit unrelated dirty files. Current worktree has many pre-existing changes and untracked files. If implementation finds conflicting edits inside planned files, stop and report conflict before overwriting.

## 5. Risk Assessment

Risk: `app/core/loosefruit_gateway.py` is incomplete in current worktree.
Mitigation: First task stabilizes ownership and imports before UI uses it.

Risk: all-location delete may require saved sessions for many LocCodes.
Mitigation: UI preflight lists missing LocCodes and runner processes one LocCode group at a time.

Risk: raw SQL DELETE would bypass Plantware validation or side effects.
Mitigation: This plan uses SQL only for SELECT target discovery and uses browser deletion for removal.

Risk: Duplicate Cleanup tab becomes too crowded.
Mitigation: Use grouped controls with scrollable or grid layout and keep one shared result table.

Risk: runner root TypeScript command can be invoked from wrong directory.
Mitigation: Verification uses `npm run build` with workdir `runner`, not root `npx tsc`.
