# Month Filter Bug Investigation - Planning Context

## Task Description
Fix Manual Adjustment API month filter bug - changing month selector to 05 still uses old month, no data returned

## Exploration Summary

Explored code flow: `fetch_records()` → `ManualAdjustmentQuery(period_month=value())` → `client.get_adjustments(query)` → API call

All code paths correctly use `.value()` to get current spinbox values at time of fetch. No stale state found.

## Key Files
- `app/ui/main_window.py` (lines 1518-1546): fetch_records() - core fetch logic  
- `app/core/api_client.py` (line 117-135): get_adjustments() - API call
- `app/core/config.py` (line 76-77): default_period_month=4, default_period_year=2026
- `configs/app.json` (lines 9-10): same defaults

## Root Cause Hypothesis
Most likely: **API server caching responses** or **missing user action**. Added debug logging needed to verify.

## Approach
Add instrumentation logging, run fetch with debug output to trace actual values, fix based on findings.

## Plan Overview

### Task 1: Add Debug Logging to Fetch Flow
- **Summary**: Add print/log statements in fetch_records() and get_adjustments() to show actual period values being sent to API
- **Files**: `app/ui/main_window.py`, `app/core/api_client.py`
- **Rationale**: Without runtime visibility, impossible to confirm whether buggy value is in UI or server layer
- **Priority**: high

### Task 2: Verify Root Cause via Runtime Inspection  
- **Summary**: Run fetch with month=05, observe debug output to identify where wrong value originates
- **DependsOn**: task-1
- **Rationale**: Identifies whether fix is in Python (UI caching) or backend (API caching)
- **Priority**: high

### Task 3: Implement Final Fix
- **Summary**: Based on findings from task 2 - implement permanent fix
- **DependsOn**: task-2
- **Rationale**: May be server caching (add cache-bust param) or UI bug (fix signal/slot)
- **Priority**: medium