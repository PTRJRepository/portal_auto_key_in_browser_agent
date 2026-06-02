# Findings and Discoveries

This document logs all findings and architectural details uncovered during the comparison logic implementation.

## Database Comparison Reference
- Source database (`db_ptrj`) contains `PR_ADTRANS` and `PR_ADTRANSLN` tables (and their corresponding historical archive tables `PR_ADTRANS_ARC` and `PR_ADTRANSLN_ARC`).
- Extended history database (`extend_db_ptrj`) contains the `payroll_manual_adjustments` table.
- In the reference TypeScript backend (`manualAdjustmentService.ts`), comparison is performed in two directions:
  1. `compareAdtransWithAdjustments`: For a given month, year, and division, it queries all employee totals in `PR_ADTRANS` (grouped by employee) for selected categories (`spsi`, `masa kerja`, `jabatan`, `premi`, etc.). It then compares each employee's totals to the records in `extend_db_ptrj.dbo.payroll_manual_adjustments`.
     - Status is `MATCH` if the amounts match (difference <= 0.01).
     - Status is `MISMATCH` if amounts differ.
     - Status is `MISSING` if the employee has a transaction in `PR_ADTRANS` but no entry in `payroll_manual_adjustments`.
  2. `reverseCompareAdtransWithAdjustments`: Compares the other way around (from `payroll_manual_adjustments` to `PR_ADTRANS`).
     - Status is `EXTRA_IN_ADJUSTMENTS` if the employee has an adjustment in `payroll_manual_adjustments` but no entry in `PR_ADTRANS`.

## Division Routing and Virtual Divisions
- Divisions are configured in `configs/divisions.json`.
- Virtual divisions (like `INF`, `NRS`, `WKS_AR`, `WKS_PG`) have `virtual: true` and specify a physical `location_code` (e.g. `P1A`, `P1B`, `AB2`).
- When querying `PR_ADTRANS` for a virtual division:
  - We look up `location_code` matching the effective physical division (e.g., `NRS` maps to `P1B`).
  - We join `HR_GANGLN` on `GangMember = EmpCode` and filter by `GangCode` matching the virtual division code or its aliases.
  - When querying `payroll_manual_adjustments` for a virtual division, we filter by the virtual division code or its resolved physical location code (e.g. `UPPER(RTRIM(division_code)) IN ('NRS', 'P1B')`).

## App Integration
- In the current workspace, `BuiltInComparisonService` only implements `reverse_compare_adtrans`.
- `division_monitor.py` calls `compare_adtrans` via the external client API (slow) and `reverse_compare_adtrans` via the built-in service.
- We need to:
  1. Implement `compare_adtrans` in `BuiltInComparisonService` inside `app/core/built_in_comparison.py`.
  2. Update `app/ui/division_monitor.py` to also use `built_in_comparison.compare_adtrans(...)` when `self.use_builtin` is True.
