# PPH21 Auto Buffer Design

## Goal

Add PPh21 as a first-class auto buffer category in the desktop app and runner.

The app must fetch, preview, run, verify, compare, and reset PPh21 rows the same way it already handles SPSI, masa kerja, and tunjangan jabatan.

## Source Contract

The source API now returns PPh21 as:

```text
adjustment_type = AUTO_BUFFER
adjustment_name = POTONGAN PPH
```

The Plantware ADCode/TaskDesc/DocDesc value for this row is:

```text
(DE) POTONGAN PPH21
```

Audit, compare, reverse-compare, and DocID lookup endpoints use the filter:

```text
pph
```

## Required Behavior

### Category

Add a new category key:

```text
pph21
```

It must be configured as:

```text
label = PPh21
adjustment_type = AUTO_BUFFER
match_contains = PPH
adcode = (DE) POTONGAN PPH21
description = (DE) POTONGAN PPH21
```

The category detector must map `POTONGAN PPH`, `POTONGAN PPH21`, and similar `AUTO_BUFFER` PPH names to `pph21`.

### Desktop UI

When `PPh21` is selected:

- `adjustment_type` becomes `AUTO_BUFFER`.
- `adjustment_name` becomes `POTONGAN PPH`.
- MISS-only remains enabled.
- adjustment-name option refresh is skipped like the other fixed auto buffer categories.

Display columns should show:

```text
Description = (DE) POTONGAN PPH21
ADCode = (DE) POTONGAN PPH21
```

The DB verification filter, duplicate cleanup filter, reset/delete filter, Division Monitor compare filter, reverse-compare filter, and sync-adtrans filter should all use:

```text
pph
```

### Division Run Dialog

Division-level runs must fetch and build payloads for `pph21` with:

```text
adjustment_type = AUTO_BUFFER
adjustment_name = POTONGAN PPH
category_key = pph21
```

### Runner

The TypeScript category registry must resolve `pph21` rows to a category strategy with:

```text
adcode = (DE) POTONGAN PPH21
description = (DE) POTONGAN PPH21
expenseCode = Labour
```

It must also resolve by record content when the fallback category is empty and the record is an AUTO_BUFFER PPH row.

### Post-Run Sync Status

Successful PPh21 rows must be included in sync-status final verification. That means `AUTO_BUFFER` rows need to be eligible for sync-status when they have an id, not only manual adjustment types.

For category-scoped sync-status calls, `pph21` must map to:

```text
adjustment_type = AUTO_BUFFER
adjustment_name = POTONGAN PPH
```

## Data Flow

```text
manual-adjustment/by-api-key
  -> category detection pph21
  -> MISS-only preview/run filtering
  -> runner selects (DE) POTONGAN PPH21
  -> Plantware input
  -> sync-status/by-api-key with AUTO_BUFFER / POTONGAN PPH
  -> compare/reverse-compare/check-adtrans use filter pph
```

## Testing

Add failing tests first for:

- Python category detection of `POTONGAN PPH`.
- `filter_for_record()` returning `pph`.
- main-window PPh21 preset values.
- display description and ADCode for PPh21.
- Division Monitor filter mapping for `pph21`.
- Division Run Dialog payload mapping for `pph21`.
- sync-status eligibility for successful AUTO_BUFFER PPh21 rows.
- TypeScript runner category resolution for `pph21`.
- duplicate cleanup category support for `pph21`.

## Out Of Scope

- Backend endpoint changes.
- PPh21 amount calculation.
- Changes to Plantware selectors or login/session behavior.
- Renaming existing category keys for SPSI, masa kerja, or tunjangan jabatan.
