# Parallel All Divisions Run Design

## Goal

Add a full-parallel batch run mode for Manual Adjustment auto key-in so the operator can run every selected division/location at the same time for the selected period and category.

Each division must run in its own browser/runner window and each division runner must use 5 tabs. The selected category remains the main data scope. `Adjustment Name = ALL` means all adjustment names under that category are included.

## Scope

In scope:

- Run all configured divisions/locations in parallel.
- Use one independent runner payload per division.
- Use `max_tabs = 5` for each division payload in this mode.
- Support a specific adjustment name or `ALL`.
- Keep session isolation per division.
- Show per-division status, row counts, completion, and failures.

Out of scope:

- Merging all divisions into one runner/browser process.
- Queueing divisions one by one.
- Changing the Plantware form-fill behavior in the TypeScript runner.
- Changing backend API contracts.

## User Flow

The operator chooses period, category, adjustment type, and adjustment name from the existing Config controls.

For full-parallel execution, the operator starts a new "Run All Divisions" action. The app creates one job per configured division. If the adjustment name control is empty or set to `ALL`, each job fetches data without sending `adjustment_name`. If a concrete adjustment name is selected, each job sends that name.

Before starting real session-reuse runs, the app checks that every target division has an active matching session file. If any required session is missing or expired, the run is blocked and the missing divisions are listed. `dry_run`, `mock`, and `fresh_login_single` do not require pre-existing sessions.

When execution starts, each division job fetches its own records, applies the same category filtering and retry-safe filtering as the current single-division flow, then starts its own runner with `division_code` set to that division and `max_tabs` set to 5.

## Architecture

Add a small batch orchestration layer in the PySide UI.

Use a per-division job model with fields:

- `division_code`
- `period_month`
- `period_year`
- `category_key`
- `adjustment_type`
- `adjustment_name`
- `runner_mode`
- `max_tabs`
- `status`
- `records_total`
- `success_count`
- `failed_count`
- `message`

The job model should reuse existing types where possible:

- `ManualAdjustmentQuery` for per-division fetches.
- `FetchWorker` logic or an extracted equivalent for API fetch and retry-safe verification.
- `RunPayload` for runner execution.
- `RunnerBridge` for each division's runner process.

Each division gets its own `QThread` and `RunnerBridge`. The UI must keep dictionaries keyed by division code for active threads, workers, bridges, and current job state.

## Data Rules

`Adjustment Name = ALL` is represented internally as `None` for API requests and payloads. The UI can display `ALL`, but API calls should omit `adjustment_name`.

Category filtering stays unchanged:

- `premi` includes `premi` and `premi_tunjangan`.
- Other categories include their matching category key.
- Existing retry-safe filtering for Premi and MISS-only behavior must remain active.

Division prefix guard still applies per division. Records rejected by the guard are logged against that division and are not sent to its runner.

## Concurrency Rules

Full parallel means all division jobs are started together after preflight passes.

Each division runner uses:

- `division_code = current division`
- `max_tabs = 5`
- `runner_mode = selected mode`
- `headless = selected headless setting`
- `only_missing_rows = selected only-missing setting`

The app must prevent starting another all-division run while one is active. Stop should request stop on every active division bridge.

## Error Handling

If fetch fails for one division, mark only that division as failed and let other divisions continue.

If runner fails for one division, mark only that division as failed and let other divisions continue.

If preflight detects missing sessions for session-reuse modes, block the whole run before any division starts.

If no records are found for a division, mark it as completed with zero records and do not start a runner for that division.

## UI

Add controls near the existing Process/job controls or a compact batch section:

- `Run All Divisions`
- `Stop All`
- A per-division status table with division, status, records, success, failed, and message.

The existing single-division run remains unchanged.

The batch status table should be the main progress surface for this mode. Existing logs can still receive detailed messages prefixed with division code.

## Testing

Add Python unit tests for:

- `ALL` adjustment name normalization omits `adjustment_name`.
- Batch job creation creates one job per configured division.
- Each payload uses its own division code and `max_tabs = 5`.
- Session preflight blocks session-reuse modes when any target division has no active session.
- Stop-all calls every active runner bridge.

Existing tests for single-division fetch, payload construction, session status, and retry-safe filtering must continue to pass.
