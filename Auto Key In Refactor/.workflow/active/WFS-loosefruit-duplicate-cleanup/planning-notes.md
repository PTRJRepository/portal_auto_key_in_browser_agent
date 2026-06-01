# Planning Notes

## User Intent
GOAL: Add a UI feature to delete duplicate Loosefruit transactions from all locations.
SCOPE: Query Gateway fetch for `db_ptrj.dbo.PR_LOOSEFRUIT`, UI controls/layout, payload routing to `delete_loosefruit`, runner/session safety, tests.
CONTEXT: User provided SQL selecting `PR_LOOSEFRUIT` rows where `DocID LIKE '%[_]%'` and asked to use it for all-location delete feature.

## Initial Findings
- Existing app has `Duplicate Cleanup` tab in `app/ui/main_window.py` with normal ADTRANS duplicate cleanup and Task Register duplicate cleanup.
- Existing Query Gateway patterns live in `app/core/query_gateway.py` and `app/core/task_register_gateway.py`.
- Existing Loosefruit browser runner already exists in `runner/src/orchestration/delete-loosefruit-runner.ts` and is routed by `runner/src/cli.ts` when payload operation is `delete_loosefruit`.
- Existing Loosefruit page automation lives in `runner/src/plantware/loosefruit-page.ts`.
- Current runner enforces one `LocCode` per Loosefruit run, so all-location UI must group targets by `LocCode` or require repeated runs per location.

## Constraints
- Planning-only workflow; no implementation in this session.
- Worktree has many unrelated modified/untracked files. Implementation must only touch planned files.
- Preserve dry-run default and confirmation before destructive delete.
