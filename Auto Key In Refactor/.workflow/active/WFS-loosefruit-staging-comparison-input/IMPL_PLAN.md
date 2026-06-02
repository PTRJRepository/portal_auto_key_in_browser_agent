# Workflow Plan: Loosefruit Staging Comparison Input

## Goal
Add/finish Auto Key In Loosefruit tab so brondol input uses staging-comparison selisih as source of truth. For each selected estate/location, app fetches sum staging, sum Plantware, and row selisih, then runner inputs positive selisih into Plantware Loose Fruit with many tabs inside one browser window/session.

## Current Findings
- pp/ui/main_window.py:1011 already adds Loosefruit Brondol tab.
- pp/ui/main_window.py:1550 builds Loosefruit UI with estate selection, staging periode, field code, rate, doc date, runner mode, max tabs, preview, run, stop, progress table, and log.
- pp/ui/main_window.py:1731 preview fetches staging comparison directly from config.api_base_url plus /backend/upah/api/staging/staging-comparison.
- pp/ui/main_window.py:1769 builds per-estate payloads with operation=input_loosefruit, loc_code, state_filter, and max_tabs.
- unner/src/cli.ts:30 dispatches operation=input_loosefruit + unner_mode=multi_tab_shared_session to unLoosefruitMultiTab; other loosefruit input uses single runner.
- unner/src/plantware/loosefruit-input.ts:298 fetches staging-comparison but hardcodes default base URL http://localhost:8002.
- unner/src/plantware/loosefruit-input.ts:316 filters rows to selisih > 0, matching estate filter, and mp_code prefix A.
- unner/src/orchestration/loosefruit-multitab-runner.ts:145 uses payload.max_tabs, capped by PLANTWARE_CONFIG.maxTabs and row count.
- Existing loosefruit duplicate cleanup workflow WFS-loosefruit-duplicate-cleanup is separate; avoid mixing delete duplicate with new input feature.

## Implementation Tasks

### IMPL-1 — Normalize staging-comparison source contract
**Files likely touched**: pp/core/api_client.py, pp/core/models.py, pp/ui/main_window.py, unner/src/types.ts, unner/src/plantware/loosefruit-input.ts

- Add one canonical config path for Loosefruit staging comparison URL/base URL.
- Support user route http://localhost:3001/upah/staging-comparison and existing route /backend/upah/api/staging/staging-comparison through config/compat adapter.
- Define response parsing for data.rows, data.totals.staging_brondol, data.totals.plantware_brondol, data.totals.selisih.
- Validate row fields: mp_code, mp_name, gang, state, staging_brondol, plantware_brondol, selisih.
- Add UI error messages for missing totals, invalid periode, HTTP failure, and empty rows.

**Acceptance**:
- Preview and runner use same endpoint/config.
- No hardcoded localhost:8002 remains as only path.
- Invalid API response gives clear message, not silent zero rows.

### IMPL-2 — Fix Loosefruit preview and source-of-truth totals
**Files likely touched**: pp/ui/main_window.py, possible new pp/core/loosefruit_staging.py, 	ests/

- Replace direct equests.get in UI preview with core helper/client so logic matches runner.
- Show per-estate total rows, sum staging, sum Plantware, sum selisih, eligible positive selisih rows.
- Keep skipped counts visible for zero/negative selisih and non-brondol employee rows.
- Cache preview result for run confirmation so user sees exact source used.
- Add guard: run disabled until preview success or explicit refresh.

**Acceptance**:
- User can see why selisih rows become input rows.
- Multiple estates preview produces correct per-estate totals.
- Tests cover positive, zero, negative, missing estate, and malformed numeric values.

### IMPL-3 — Harden single-window multi-tab runner
**Files likely touched**: unner/src/orchestration/loosefruit-multitab-runner.ts, unner/src/orchestration/loosefruit-input-runner.ts, unner/src/plantware/loosefruit-input.ts, unner/src/types.ts

- Keep invariant: one payload estate/location = one BrowserSession = one browser window/context; max_tabs = pages/tabs inside that window.
- Ensure all assigned rows in one run share same loc_code/estate; reject mixed estate rows unless explicitly grouped before session start.
- Improve row assignment to avoid duplicate employees across tabs and keep emitted totals correct.
- Ensure per-tab failure only fails that tab’s remaining rows; other tabs continue.
- Emit consistent events: loosefruit.multitab.tab.assigned, loosefruit.multitab.row.started, loosefruit.multitab.row.success, loosefruit.multitab.row.skipped, loosefruit.multitab.row.failed, esult.
- Verify deriveTaskCodeFromLoc(loc_code) and deriveDivisionFromGang(row.gang) match Plantware expected values for P1A/P1B/P2A/P2B.

**Acceptance**:
- One selected estate uses one browser window/session and many tabs.
- Many selected estates run isolated sessions/windows sequentially or via explicit safe queue.
- No row can be input twice because another tab already added it.

### IMPL-4 — Wire UI run lifecycle and safety gates
**Files likely touched**: pp/ui/main_window.py, pp/core/runner_bridge.py, pp/core/run_artifacts.py

- Reuse RunnerBridge instead of separate LoosefruitRunWorker if feasible, to match event parsing/artifacts used by other runners.
- Add session check per selected estate before run: if session missing, tell user to run Get Session for that estate.
- Add confirmation summary before actual run: estates, tabs per estate, eligible rows, total MT/selisih, rate, doc date.
- Improve stop behavior: terminate current runner, mark current estate stopped, leave next estates pending/not run.
- Persist events/result in run artifacts if current artifacts framework supports non-manual-adjustment operations.

**Acceptance**:
- UI status/progress matches runner events and final result.
- Stop button does not launch next estate after stop.
- Missing session blocks run before browser starts.

### IMPL-5 — Test and validation package
**Files likely touched**: 	ests/, unner/src/orchestration/*.test.ts, unner/src/plantware/*.test.ts, docs/README if needed

- Python tests for staging response normalization, preview filtering, and payload creation.
- TypeScript tests for ilterLooseFruitRows, row assignment, mixed-estate guard, and result counting.
- Build runner with 
pm run build under unner.
- Run Python tests with pytest from repo root.
- Add README section for Loosefruit: endpoint config, session rule, tab rule, input rule.

**Acceptance**:
- pytest passes for changed Python tests.
- 
pm run build passes under unner.
- Runner unit tests pass if project has test command or via direct test runner setup.

## Execution Order
1. Review current uncommitted diffs before editing any source file.
2. Implement IMPL-1 source contract first.
3. Implement IMPL-2 preview using same helper/client.
4. Implement IMPL-3 runner hardening with tests.
5. Implement IMPL-4 UI lifecycle/safety.
6. Implement IMPL-5 tests/docs and run validation.

## Conflict / Safety Notes
- git status shows existing modified files: pp/core/built_in_comparison.py, pp/core/models.py, pp/ui/division_monitor.py, pp/ui/main_window.py, unner/src/cli.ts, unner/src/types.ts, plus generated __pycache__ and many untracked files.
- Do not overwrite or revert WIP. Inspect git diff -- <file> before editing overlapping files.
- Coordinate with active workflow WFS-premi-remarks-sync-missing because it also touches UI/payload categories.
- Keep duplicate cleanup workflow separate from Loosefruit input workflow.

## Open Questions
- Which endpoint is canonical for production: http://localhost:3001/upah/staging-comparison or /backend/upah/api/staging/staging-comparison?
- Does route require API key/header from Auto Key In config?
- Should negative selisih ever trigger delete/reset, or only positive selisih input?
- Should multiple estates run sequentially only, or can app launch multiple browser windows in parallel with separate sessions?
- Are task code CT2202{LocCode}, rate 1750, and field code space default valid for all estates?
