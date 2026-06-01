# Planning Context: Loosefruit Duplicate Deletion

## Source Evidence
- `exploration-patterns.json` - _build_duplicate_cleanup_tab() at L1122-L1206 is canonical PySide6 pattern: QGroupBox/QFormLayout, QSpinBox period controls, QLineEdit filters, QCheckBox dry_run, fetch+delete button row, QTableWidget with checkbox column
- `exploration-dependencies.json` - Empty (no cross-component dependencies beyond existing patterns)
- `exploration-integration-points.json` - Empty (integration fully via existing PlantwareDbPtrjGateway)
- `app/core/query_gateway.py:129-178` - execute() and fetch_all() methods are the SQL execution primitive; add loosefruit methods as thin wrappers
- `app/ui/main_window.py:619-687` - DuplicateFetchWorker and TaskRegisterFetchWorker QObject/QThread pattern for async fetch
- `app/ui/main_window.py:2306-2331` - fetch_task_register_duplicate_targets() pattern showing QThread spawn, signal wiring, thread cleanup

## Understanding
- **Current State**: Duplicate cleanup tab has two sections (Plantware DocID + Task Register DocID). PR_LOOSEFRUIT table has duplicate records identified by DocID containing underscore `_`, scanned via Query Gateway HTTP SQL runner.
- **Problem**: Need to add a third section in the Duplicate Cleanup tab to scan/delete loosefruit duplicates across all LocCode values, using the existing PlantwareDbPtrjGateway SQL runner (no browser automation needed).
- **Approach**: Add two thin methods to query_gateway.py, then add a third QGroupBox to _build_duplicate_cleanup_tab() following the identical QFormLayout pattern as Task Register section, with its own fetch+delete button row and dedicated QTableWidget.

## Key Decisions
- Decision: Use existing PlantwareDbPtrjGateway.execute() / fetch_all() | Rationale: No new config or runner needed; PR_LOOSEFRUIT is on the same db_ptrj server | Evidence: app/core/query_gateway.py:91-178
- Decision: Add dedicated QTableWidget (7 columns: Select, DocID, LocCode, DocDate, Status, TotalMT, Message) instead of reusing duplicate_table | Rationale: Loosefruit has different columns (TotalMT vs Emp/Loc), no Keep DocID column, keeping UI separation cleaner | Evidence: task description specifies 7 columns
- Decision: dry_run defaults True | Rationale: Matches existing duplicate cleanup behavior (controls.setChecked(True)) | Evidence: app/ui/main_window.py:1183-1184
- Decision: LocCode filter = empty means scan ALL locations | Rationale: PR_LOOSEFRUIT can have duplicates across all LocCode values, scan all by default | Evidence: task description: "Delete from ALL locations"
- Decision: No new QThread worker class needed for delete | Rationale: Delete is single-record async HTTP call, simple signal/slot per record inline is sufficient | Evidence: task description: "SQL DELETE via query gateway"

## Dependencies
- Depends on: None (standalone feature, follows established patterns)
- Provides for: Enables loosefruit duplicate cleanup in Duplicate Cleanup tab, using existing infrastructure