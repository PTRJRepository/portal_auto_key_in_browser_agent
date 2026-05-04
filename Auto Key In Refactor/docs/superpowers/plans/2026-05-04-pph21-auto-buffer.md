# PPH21 Auto Buffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PPh21 as an AUTO_BUFFER category that can be fetched, run, verified, compared, and reset like SPSI, masa kerja, and tunjangan jabatan.

**Architecture:** Extend the existing category registry pattern instead of introducing a new abstraction. Python owns desktop UI category selection, API filters, and sync-status scope; TypeScript owns Plantware category strategy resolution.

**Tech Stack:** Python 3.10+, PySide6, pytest, TypeScript, Playwright runner, Node test scripts executed with `tsx`.

---

## File Structure

- Modify `configs/adjustment-categories.json`: add `pph21` AUTO_BUFFER category.
- Modify `app/ui/main_window.py`: add PPh21 preset, filter mapping, AUTO_BUFFER sync-status eligibility, display ADCode behavior, and category sync-status scope.
- Modify `app/ui/division_monitor.py`: map `pph21` to compare/reverse-compare filter `pph`.
- Modify `app/ui/division_run_dialog.py`: map `pph21` to `AUTO_BUFFER / POTONGAN PPH` for fetch and run payloads.
- Modify `runner/src/categories/registry.ts`: add TypeScript `pph21` strategy.
- Modify `runner/src/orchestration/delete-duplicates-runner.ts`: allow duplicate cleanup for `pph21`.
- Modify `docs/DESCRIPTION-RULES.md`: document the new AUTO_BUFFER DocDesc rule.
- Modify `tests/test_api_models.py`: add Python tests for registry, UI, filters, dialog payload, and sync-status ids.
- Modify `runner/src/categories/registry-smoke.test.ts`: add TypeScript runner category assertion.
- Modify `runner/src/orchestration/delete-duplicates-runner.test.ts`: add duplicate cleanup support assertion.

---

### Task 1: Python Category Config and Core Filter Mapping

**Files:**
- Modify: `configs/adjustment-categories.json`
- Modify: `app/ui/main_window.py`
- Test: `tests/test_api_models.py`

- [ ] **Step 1: Write failing Python tests for category detection and filter mapping**

Append these tests near the existing category/filter tests in `tests/test_api_models.py`:

```python
def test_category_registry_detects_pph21_auto_buffer_name():
    registry = CategoryRegistry([
        AdjustmentCategory("pph21", "PPh21", "AUTO_BUFFER", ("PPH",), "(DE) POTONGAN PPH21", "(DE) POTONGAN PPH21"),
    ])

    assert registry.detect("POTONGAN PPH", "AUTO_BUFFER") == "pph21"
    assert registry.detect("POTONGAN PPH21", "AUTO_BUFFER") == "pph21"


def test_filter_for_record_maps_pph21_to_pph():
    from app.ui.main_window import filter_for_record

    record = normalize_record({
        "adjustment_type": "AUTO_BUFFER",
        "adjustment_name": "POTONGAN PPH",
        "amount": 93435,
    }, "pph21")

    assert filter_for_record(record) == "pph"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_category_registry_detects_pph21_auto_buffer_name tests/test_api_models.py::test_filter_for_record_maps_pph21_to_pph -v
```

Expected: `test_filter_for_record_maps_pph21_to_pph` fails because `filter_for_record()` returns `pph21` or a fallback name, not `pph`.

- [ ] **Step 3: Add PPh21 category config**

Insert this item after `tunjangan_jabatan` in `configs/adjustment-categories.json`:

```json
{"key":"pph21","label":"PPh21","adjustment_type":"AUTO_BUFFER","match_contains":["PPH"],"adcode":"(DE) POTONGAN PPH21","description":"(DE) POTONGAN PPH21"}
```

- [ ] **Step 4: Add PPh21 filter mapping**

In `app/ui/main_window.py`, update `filter_for_record()`:

```python
def filter_for_record(record: ManualAdjustmentRecord) -> str:
    category_key = record.category_key or ""
    if category_key == "masa_kerja":
        return "masa kerja"
    if category_key == "tunjangan_jabatan":
        return "jabatan"
    if category_key == "pph21":
        return "pph"
    if category_key == "potongan_upah_kotor":
        return "potongan"
    if category_key == "potongan_upah_bersih":
        return "potongan upah bersih"
    if category_key == "premi_tunjangan":
        return "premi"
    if category_key == "premi":
        return "premi"
    if category_key:
        return category_key
    name = record.adjustment_name.strip()
    return (name[5:] if name.upper().startswith("AUTO ") else name).lower()
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_category_registry_detects_pph21_auto_buffer_name tests/test_api_models.py::test_filter_for_record_maps_pph21_to_pph -v
```

Expected: both tests pass.

---

### Task 2: Main Window PPh21 UI and Sync-Status Eligibility

**Files:**
- Modify: `app/ui/main_window.py`
- Test: `tests/test_api_models.py`

- [ ] **Step 1: Write failing main-window tests**

Append these tests near existing preset and sync-status tests in `tests/test_api_models.py`:

```python
def test_pph21_preset_sets_auto_buffer_scope_and_display_values():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("pph21", "PPh21", "AUTO_BUFFER", ("PPH",), "(DE) POTONGAN PPH21", "(DE) POTONGAN PPH21"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.category.setCurrentIndex(window.category.findData("pph21"))
    window.apply_category_preset()

    record = normalize_record({
        "id": 90,
        "adjustment_type": "AUTO_BUFFER",
        "adjustment_name": "POTONGAN PPH",
        "amount": 93435,
    }, "pph21")

    assert window.adjustment_type.currentText() == "AUTO_BUFFER"
    assert window.adjustment_name.text() == "POTONGAN PPH"
    assert window.only_missing.isChecked() is True
    assert window._adjustment_name_option_type() is None
    assert window._default_filter_for_category_key("pph21") == "pph"
    assert window._description_for_record(record) == "(DE) POTONGAN PPH21"
    assert window._adcode_for_record(record) == "(DE) POTONGAN PPH21"
    window.close()


def test_sync_status_helpers_include_auto_buffer_pph21_ids():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("pph21", "PPh21", "AUTO_BUFFER", ("PPH",), "(DE) POTONGAN PPH21", "(DE) POTONGAN PPH21"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    record = normalize_record({
        "id": 90,
        "adjustment_type": "AUTO_BUFFER",
        "adjustment_name": "POTONGAN PPH",
        "amount": 93435,
    }, "pph21")
    payload = RunPayload(
        period_month=4,
        period_year=2026,
        division_code="P1B",
        gang_code=None,
        emp_code=None,
        adjustment_type="AUTO_BUFFER",
        adjustment_name="POTONGAN PPH",
        category_key="pph21",
        runner_mode="mock",
        max_tabs=1,
        headless=True,
        only_missing_rows=True,
        row_limit=None,
        records=[record],
    )

    window.records = [record]
    assert sync_status_ids_for_records([record]) == [90]
    assert window._sync_status_id_for_record(record) == 90
    assert window._sync_status_adjustment_type_for_ids({90}) == "AUTO_BUFFER"
    assert window._sync_status_scope_for_category("pph21", payload) == ("AUTO_BUFFER", "POTONGAN PPH")
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_pph21_preset_sets_auto_buffer_scope_and_display_values tests/test_api_models.py::test_sync_status_helpers_include_auto_buffer_pph21_ids -v
```

Expected: failures show missing `pph21` preset/filter mapping and `AUTO_BUFFER` not eligible for sync-status ids.

- [ ] **Step 3: Update fixed AUTO_BUFFER category set**

Add this module constant near `PREMI_CATEGORY_KEYS` in `app/ui/main_window.py`:

```python
AUTO_BUFFER_CATEGORY_KEYS = {"spsi", "masa_kerja", "tunjangan_jabatan", "pph21"}
SYNC_STATUS_ADJUSTMENT_TYPES = {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "AUTO_BUFFER"}
```

Keep `PREMI_CATEGORY_KEYS`, `MANUAL_PREVIEW_CATEGORY_KEYS`, and `MANUAL_ADJUSTMENT_OPTION_TYPES` unchanged.

- [ ] **Step 4: Add PPh21 preset**

In `MainWindow.apply_category_preset()`, add this branch after `tunjangan_jabatan`:

```python
elif category_key == "pph21":
    self.adjustment_type.setCurrentText("AUTO_BUFFER")
    self._set_adjustment_name_options(["POTONGAN PPH"], "POTONGAN PPH")
    self.only_missing.setChecked(True)
```

- [ ] **Step 5: Skip adjustment-name refresh for PPh21**

In `_adjustment_name_option_type()`, replace:

```python
if category_key in {"spsi", "masa_kerja", "tunjangan_jabatan"}:
    return None
```

with:

```python
if category_key in AUTO_BUFFER_CATEGORY_KEYS:
    return None
```

- [ ] **Step 6: Add sync-status category scope**

In `_sync_status_scope_for_category()`, add:

```python
if category_key == "pph21":
    return "AUTO_BUFFER", "POTONGAN PPH"
```

- [ ] **Step 7: Allow AUTO_BUFFER records with ids through sync-status helpers**

Because `SYNC_STATUS_ADJUSTMENT_TYPES` now includes `AUTO_BUFFER`, keep `_start_sync_status_update_for_successful_records()`, `_sync_status_id_for_record()`, `_sync_status_adjustment_type_for_ids()`, and `_queue_sync_status_for_record()` structurally unchanged. Their existing type checks will include PPh21 once the constant changes.

- [ ] **Step 8: Add default filter and ADCode behavior**

In `_default_filter_for_category_key()`, add:

```python
"pph21": "pph",
```

In `_adcode_for_record()`, replace the hardcoded AUTO_BUFFER category set:

```python
is_auto_buffer = record.adjustment_type == "AUTO_BUFFER" or (record.category_key or "") in {"spsi", "masa_kerja", "tunjangan_jabatan"}
```

with:

```python
is_auto_buffer = record.adjustment_type == "AUTO_BUFFER" or (record.category_key or "") in AUTO_BUFFER_CATEGORY_KEYS
```

- [ ] **Step 9: Run tests to verify they pass**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_pph21_preset_sets_auto_buffer_scope_and_display_values tests/test_api_models.py::test_sync_status_helpers_include_auto_buffer_pph21_ids -v
```

Expected: both tests pass.

---

### Task 3: Division Monitor and Division Run Dialog PPh21 Flows

**Files:**
- Modify: `app/ui/division_monitor.py`
- Modify: `app/ui/division_run_dialog.py`
- Test: `tests/test_api_models.py`

- [ ] **Step 1: Write failing tests for monitor and dialog mappings**

Append these tests in `tests/test_api_models.py`:

```python
def test_division_monitor_maps_pph21_filter():
    from app.ui.division_monitor import FILTER_TO_CATEGORY, filters_for_categories

    assert filters_for_categories(["pph21"]) == ["pph"]
    assert FILTER_TO_CATEGORY["pph"] == "pph21"


def test_division_run_dialog_builds_pph21_auto_buffer_payload():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("pph21", "PPh21", "AUTO_BUFFER", ("PPH",), "(DE) POTONGAN PPH21", "(DE) POTONGAN PPH21"),
    ])
    dialog = DivisionRunDialog(
        config=config,
        categories=registry,
        api_client=Mock(),
        division_code="P1B",
        division_label="Estate",
        category_key="pph21",
        category_label="PPh21",
        mode="mock",
        month=4,
        year=2026,
    )

    payload = dialog._build_payload("mock", [])

    assert payload.adjustment_type == "AUTO_BUFFER"
    assert payload.adjustment_name == "POTONGAN PPH"
    assert payload.category_key == "pph21"
    dialog.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_division_monitor_maps_pph21_filter tests/test_api_models.py::test_division_run_dialog_builds_pph21_auto_buffer_payload -v
```

Expected: monitor mapping misses `pph21`; dialog payload has `adjustment_name is None`.

- [ ] **Step 3: Add Division Monitor mapping**

In `app/ui/division_monitor.py`, update `CATEGORY_TO_FILTERS`:

```python
"pph21": ["pph"],
```

Update `FILTER_TO_CATEGORY`:

```python
"pph": "pph21",
```

- [ ] **Step 4: Add Division Run Dialog PPh21 adjustment names**

In both `_start_workflow()` and `_build_payload()` in `app/ui/division_run_dialog.py`, add this branch after `tunjangan_jabatan`:

```python
elif self.category_key == "pph21":
    adjustment_name = "POTONGAN PPH"
```

In `_sync_missing()` filter map, add:

```python
"pph21": ["pph"],
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_division_monitor_maps_pph21_filter tests/test_api_models.py::test_division_run_dialog_builds_pph21_auto_buffer_payload -v
```

Expected: both tests pass.

---

### Task 4: TypeScript Runner PPh21 Strategy and Duplicate Support

**Files:**
- Modify: `runner/src/categories/registry.ts`
- Modify: `runner/src/categories/registry-smoke.test.ts`
- Modify: `runner/src/orchestration/delete-duplicates-runner.ts`
- Modify: `runner/src/orchestration/delete-duplicates-runner.test.ts`

- [ ] **Step 1: Write failing TypeScript tests**

Add this to `runner/src/categories/registry-smoke.test.ts`:

```typescript
const pph21Record = record("pph21", "POTONGAN PPH", "POTONGAN PPH | (DE) POTONGAN PPH21 | 93435", { adjustment_type: "AUTO_BUFFER" });
const pph21 = resolveCategory(pph21Record, "pph21");
assert.equal(pph21.adcode(pph21Record), "(DE) POTONGAN PPH21");
assert.equal(pph21.description(pph21Record), "(DE) POTONGAN PPH21");
assert.equal(resolveCategory({ ...pph21Record, category_key: "" }, "").key, "pph21");
```

Add this to `runner/src/orchestration/delete-duplicates-runner.test.ts` after the other supported category assertions:

```typescript
assert.equal(duplicateCleanupCategorySupported("pph21"), true);
```

- [ ] **Step 2: Run TypeScript tests to verify they fail**

Run:

```powershell
npx --prefix runner tsx runner/src/categories/registry-smoke.test.ts
npx --prefix runner tsx runner/src/orchestration/delete-duplicates-runner.test.ts
```

Expected: registry test throws unsupported category or cannot resolve; duplicate cleanup test returns `false`.

- [ ] **Step 3: Add TypeScript PPh21 strategy**

In `runner/src/categories/registry.ts`, add this object after `tunjangan_jabatan`:

```typescript
  {
    key: "pph21",
    adcode: () => "(DE) POTONGAN PPH21",
    matches: (record) => record.adjustment_type === "AUTO_BUFFER" && record.adjustment_name.toUpperCase().includes("PPH"),
    description: () => "(DE) POTONGAN PPH21",
    expenseCode: labourExpense
  },
```

Update the comment block above strategies to include:

```typescript
 * - PPh21        -> "(DE) POTONGAN PPH21"
```

- [ ] **Step 4: Add duplicate cleanup support**

In `runner/src/orchestration/delete-duplicates-runner.ts`, add `"pph21"` to `DUPLICATE_CLEANUP_CATEGORIES`:

```typescript
  "pph21",
```

- [ ] **Step 5: Run TypeScript tests to verify they pass**

Run:

```powershell
npx --prefix runner tsx runner/src/categories/registry-smoke.test.ts
npx --prefix runner tsx runner/src/orchestration/delete-duplicates-runner.test.ts
```

Expected: both commands exit `0`.

---

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `docs/DESCRIPTION-RULES.md`
- Verify: Python and TypeScript test/build commands

- [ ] **Step 1: Update description rules doc**

In `docs/DESCRIPTION-RULES.md`, update the AUTO_BUFFER table to include:

```markdown
| `pph21` | POTONGAN PPH | **(DE) POTONGAN PPH21** |
```

Update the explanation list:

```markdown
- **PPh21** diinput sebagai **(DE) POTONGAN PPH21** karena Plantware memakai TaskDesc deduction employee tersebut.
```

Update the implementation snippets:

```typescript
// PPh21
description: () => "(DE) POTONGAN PPH21"
```

Update the notes:

```markdown
- Adcode tetap menggunakan: `spsi`, `masa kerja`, `tunjangan jabatan`, dan `(DE) POTONGAN PPH21`.
```

- [ ] **Step 2: Run targeted Python tests**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/test_api_models.py::test_category_registry_detects_pph21_auto_buffer_name tests/test_api_models.py::test_filter_for_record_maps_pph21_to_pph tests/test_api_models.py::test_pph21_preset_sets_auto_buffer_scope_and_display_values tests/test_api_models.py::test_sync_status_helpers_include_auto_buffer_pph21_ids tests/test_api_models.py::test_division_monitor_maps_pph21_filter tests/test_api_models.py::test_division_run_dialog_builds_pph21_auto_buffer_payload -v
```

Expected: all targeted Python tests pass.

- [ ] **Step 3: Run full Python test suite**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests -v
```

Expected: all Python tests pass.

- [ ] **Step 4: Run TypeScript targeted tests**

Run:

```powershell
npx --prefix runner tsx runner/src/categories/registry-smoke.test.ts
npx --prefix runner tsx runner/src/orchestration/delete-duplicates-runner.test.ts
```

Expected: both commands exit `0`.

- [ ] **Step 5: Build TypeScript runner**

Run:

```powershell
npm --prefix runner run build
```

Expected: TypeScript build exits `0`.

- [ ] **Step 6: Commit implementation**

Stage only files touched for this feature:

```powershell
git add -- configs/adjustment-categories.json app/ui/main_window.py app/ui/division_monitor.py app/ui/division_run_dialog.py runner/src/categories/registry.ts runner/src/categories/registry-smoke.test.ts runner/src/orchestration/delete-duplicates-runner.ts runner/src/orchestration/delete-duplicates-runner.test.ts docs/DESCRIPTION-RULES.md tests/test_api_models.py docs/superpowers/plans/2026-05-04-pph21-auto-buffer.md
git commit -m "feat: add pph21 auto buffer support"
```

Expected: commit succeeds with only PPh21-related files staged.
