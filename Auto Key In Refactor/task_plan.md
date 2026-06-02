# Task Plan: Compare and Find Missing/Synced Premium and Auto Buffer Data

## Goal
Implement a mechanism to compare data between `extend_db_ptrj` and `db_ptrj` (specifically for premium and auto buffer) to identify synchronized vs. missing (miss) data based on location codes (estate/division). The logic should be studied from the reference path: `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production`.

---

## Phases

### Phase 1: Research and Analysis
- [x] Inspect files in the reference directory `D:\Gawean Rebinmas\PORTAL_ESTATE\Plantware_Auto_Report\Daftar_Upah_baru\payroll_daftar_upah\refactor_production` to understand the current DB comparison logic.
- [x] Inspect the database structures (`extend_db_ptrj` vs `db_ptrj`) or query patterns used to find the difference between the two DBs.
- [x] Log findings in `findings.md`.

### Phase 2: Design and Sandbox Prototype
- [x] Design the SQL query or python-based comparison logic that detects missing (miss) and synchronized records.
- [x] Create a prototype script in `_dev_utils/explorations/` or `_dev_utils/tests/` to verify the logic.
- [x] Test the query and compare output.

### Phase 3: Integration into main application
- [x] Implement/integrate the database comparison mechanism into the main application (`app/core/built_in_comparison.py`).
- [x] Update configs or database connection setups if necessary (not needed, `AppConfig` already has all config variables).
- [x] Ensure proper API endpoints or service modules exist to serve this data (`division_monitor.py` updated to call built-in service).

### Phase 4: Verification and Testing
- [x] Write integration/unit tests for the comparison logic in `_dev_utils/tests/test_built_in_comparison.py`.
- [ ] Verify the performance and correctness using full test suite.
- [ ] Review UI/API response structure.

---

## Decisions and Notes
- Implemented `compare_adtrans` in `BuiltInComparisonService` to query `db_ptrj` and `extend_db_ptrj` directly using SQL, replicating node-mssql SQL query structure from TypeScript.
- Disables flask plugin for python 3.10 pytest using `-p no:flask` to bypass a compatibility issue with Flask 3.x stack exports.

## Errors Encountered
| Error | Phase | Attempt | Resolution |
|-------|-------|---------|------------|
| TypeError: QueryGatewayResult.__init__() missing 1 required positional argument: 'raw' | Phase 4 | 1 | Passed empty dictionary as raw argument to `QueryGatewayResult` constructor. |
| ModuleNotFoundError: No module named 'PySide6' | Phase 4 | 1 | Ran tests using `python3` command (which points to python 3.10 containing PySide6). |
| ImportError: cannot import name '_request_ctx_stack' from 'flask' | Phase 4 | 1 | Ran pytest with `-p no:flask` to disable the conflicting pytest-flask plugin. |
