# MISS-Only Input and DIFF Reset Design

## Goal

Make the desktop app separate two operational states:

- `MISS` / `MISSING` means the row can be fetched and run for auto key-in.
- `DIFF` / `MISMATCH` means Plantware already has a transaction with the wrong amount, so it must be reset/deleted first and must not be sent to auto key-in.

After a DIFF reset/delete, the app must refresh the manual-adjustment audit status so the affected scope becomes `sync:MISS | match:MISMATCH`, ready for the next MISS-only run.

## Current Behavior

The main process tab has a checkbox labeled `Input MISS/MISMATCH only`. For non-premium categories the fetch filter ignores manual categories, and helper logic can treat stale `match:MISMATCH` rows as eligible. Division Monitor also syncs compare results with `sync_mode="MISMATCH_AND_MISSING"`, which updates mismatched rows in `extend_db_ptrj` instead of preserving the reset-first workflow.

The Reset/Delete DocID tab can fetch DocIDs from `adtrans-doc-ids/by-api-key`, but that endpoint does not compare Plantware amount against manual adjustment amount. The endpoint documentation says mismatch cleanup must use `compare-adtrans/by-api-key` and read DocIDs from `db_ptrj_doc_desc_details[]`.

## Required Behavior

### MISS Input

The process tab filter becomes MISS-only. It must include only rows where the current audit says Plantware is missing the transaction:

- `sync:MISS`
- `sync:MISSING`
- `VERIFIED_NOT_FOUND`
- premium sync-status dry-run rows that resolve to `NOT_FOUND`

It must exclude:

- `sync:DIFF`
- `match:MISMATCH` when ADTRANS amount is non-zero
- `VERIFIED_MISMATCH`
- `DB Mismatch`

This applies to manual categories as well as AUTO_BUFFER categories. `MATCH` and `SYNC` rows remain skipped.

### DIFF Reset/Delete

The Reset/Delete DocID tab uses only a DIFF/MISMATCH fetch mode. It calls:

```text
POST /payroll/manual-adjustment/compare-adtrans/by-api-key
```

with the active period, division, and category filters. It keeps only `status == "MISMATCH"` comparisons and converts every non-empty `db_ptrj_doc_desc_details[].doc_id` into a `DELETE_RECORD` target. Duplicate DocIDs are removed.

The tab must not use `adtrans-doc-ids/by-api-key` for this delete flow because that endpoint does not compare nominal values. That endpoint can remain in the API client for other maintenance flows, but the reset/delete UI should target DIFF/MISMATCH only.

### Audit After Delete

After reset/delete runner completes for DIFF targets, the app calls:

```text
POST /payroll/manual-adjustment/sync-status/by-api-key
```

for the same period/division/category scope with:

```json
{
  "dry_run": false,
  "only_if_adtrans_exists": true,
  "updated_by": "browser_automation"
}
```

Because the Plantware transaction has been deleted, the endpoint should update affected rows to:

```text
sync:MISS | match:MISMATCH
```

If delete was a dry run, the app must not apply the audit update.

### Division Monitor Sync

Division Monitor sync must not overwrite mismatches by default. Its sync action becomes missing-only:

```json
{
  "sync_mode": "MISSING_ONLY"
}
```

This inserts missing manual adjustment rows from Plantware without updating mismatched manual adjustment rows. Mismatches remain visible for reset/delete.

## UI Changes

- Rename process checkbox text to `Input MISS only`.
- Update tooltip to state that DIFF/MISMATCH is excluded and must be handled from Reset/Delete DocID.
- The Reset/Delete source is fixed to `DIFF/MISMATCH DocIDs`.
- Reset table status text should say targets came from mismatch compare.

## Data Flow

MISS run:

```text
manual-adjustment/by-api-key
  -> optional sync-status/check-adtrans verification
  -> MISS-only filter
  -> runner auto key-in
  -> sync-status final verification
```

DIFF reset:

```text
compare-adtrans/by-api-key
  -> MISMATCH comparisons
  -> db_ptrj_doc_desc_details[].doc_id
  -> runner delete/reset
  -> sync-status apply
  -> rows become sync:MISS
```

## Testing

Add focused tests for:

- `record_is_stale_miss` excludes `DIFF` and `match:MISMATCH`.
- main fetch filtering includes MISS and excludes DIFF/MISMATCH for manual categories.
- API client converts `compare-adtrans` mismatch details into `DELETE_RECORD` targets.
- Reset/Delete DIFF mode chooses compare endpoint instead of `adtrans-doc-ids`.
- Division Monitor sync uses `MISSING_ONLY`.
- Post-delete audit update is triggered only after non-dry-run reset/delete.

## Out Of Scope

- Backend endpoint changes.
- Plantware delete button implementation changes.
- A broad refactor of the large PySide `main_window.py` file.
