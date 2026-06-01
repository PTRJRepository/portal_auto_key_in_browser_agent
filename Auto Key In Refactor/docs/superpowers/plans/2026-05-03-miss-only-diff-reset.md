# MISS-Only DIFF Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate MISS-only auto key-in from DIFF/MISMATCH reset/delete, then refresh deleted DIFF rows back to MISS.

**Architecture:** Keep the existing PySide screens and runner contract. Add a compare-based DocID target extractor in the API client, expose it as a Reset/Delete source mode, tighten MISS classification, and run a scoped `sync-status` audit after actual DIFF deletes.

**Tech Stack:** Python 3.11, PySide6, pytest, existing Manual Adjustment API client, existing Playwright runner delete operation.

---

## File Structure

- Modify `Auto Key In Refactor/app/core/api_client.py`: add compare-based mismatch DocID target fetching.
- Modify `Auto Key In Refactor/app/ui/main_window.py`: rename process filter, apply MISS-only filtering, add Reset/Delete source mode, trigger post-delete audit.
- Modify `Auto Key In Refactor/app/ui/division_monitor.py`: switch sync action to `MISSING_ONLY`.
- Modify `Auto Key In Refactor/app/ui/division_run_dialog.py`: switch standalone sync action to `MISSING_ONLY`.
- Modify `Auto Key In Refactor/tests/test_api_models.py`: add regression tests for filter, compare DocID extraction, reset source branching, and sync modes.
- Modify `Auto Key In Refactor/README.md`: document MISS vs DIFF workflow.

---

### Task 1: Tighten MISS Classification

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove `DIFF` and `match:MISMATCH` are not considered MISS, while `sync:MISS` is.

```python
def test_record_is_stale_miss_excludes_diff_and_mismatch():
    from app.ui.main_window import record_is_stale_miss

    miss = normalize_record({"remarks": "AUTO SPSI | spsi | 4000 | sync:MISS | match:MISMATCH"}, "spsi")
    diff = normalize_record({"remarks": "AUTO SPSI | spsi | 4000 | sync:DIFF | match:MISMATCH"}, "spsi")
    mismatch = normalize_record({"remarks": "AUTO SPSI | spsi | 4000 | sync:MANUAL | match:MISMATCH"}, "spsi")

    assert record_is_stale_miss(miss) is True
    assert record_is_stale_miss(diff) is False
    assert record_is_stale_miss(mismatch) is False
```

Add a UI filtering test for manual categories.

```python
def test_manual_fetch_miss_only_excludes_diff_records():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("potongan_upah_kotor", "Potongan", "POTONGAN_KOTOR", ("POTONGAN", "KOREKSI"), "potongan"),
    ])
    window = MainWindow(AppConfig(default_division_code="P1B"), registry, [DivisionOption("P1B", "Estate")])
    window.category.setCurrentIndex(window.category.findData("potongan_upah_kotor"))
    window.process_only_miss.setChecked(True)
    miss = normalize_record({
        "emp_code": "B0001",
        "gang_code": "B1H",
        "division_code": "P1B",
        "adjustment_type": "POTONGAN_KOTOR",
        "adjustment_name": "KOREKSI PANEN",
        "amount": 1000,
        "remarks": "KOREKSI PANEN | DE0001 | 1000 | sync:MISS | match:MISMATCH",
    }, "potongan_upah_kotor")
    diff = normalize_record({
        "emp_code": "B0002",
        "gang_code": "B1H",
        "division_code": "P1B",
        "adjustment_type": "POTONGAN_KOTOR",
        "adjustment_name": "KOREKSI PANEN",
        "amount": 2000,
        "remarks": "KOREKSI PANEN | DE0001 | 2000 | sync:DIFF | match:MISMATCH",
    }, "potongan_upah_kotor")

    window._handle_fetch_completed([miss, diff], {})

    assert [record.emp_code for record in window.records] == ["B0001"]
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_api_models.py::test_record_is_stale_miss_excludes_diff_and_mismatch tests/test_api_models.py::test_manual_fetch_miss_only_excludes_diff_records -q
```

Expected: both tests fail because current logic includes mismatch/manual categories.

- [ ] **Step 3: Implement minimal code**

Change `record_is_stale_miss`:

```python
def record_is_stale_miss(record: ManualAdjustmentRecord) -> bool:
    sync_status = sync_status_from_remarks(record).upper()
    if sync_status == "SYNC":
        return False
    return sync_status in {"MISS", "MISSING", "NOT_FOUND"}
```

Change `_handle_fetch_completed` so `process_only_miss` applies to non-premium manual categories too:

```python
elif self.process_only_miss.isChecked():
    before_miss_filter = len(filtered_records)
    filtered_records = [record for record in filtered_records if self._record_is_miss(record)]
    miss_filter_applied = True
    self.append_log(
        f"MISS-only filter active: {len(filtered_records)} of {before_miss_filter} category records will be previewed/run."
    )
```

Update checkbox label and tooltip:

```python
self.process_only_miss = QCheckBox("Input MISS only")
self.process_only_miss.setToolTip("Jika aktif, fetch/run hanya memakai MISS. DIFF/MISMATCH harus dihapus dulu dari Reset/Delete DocID.")
```

- [ ] **Step 4: Run tests to verify pass**

Run the same pytest command. Expected: pass.

---

### Task 2: Add Compare-Based DIFF DocID Targets

**Files:**
- Modify: `Auto Key In Refactor/app/core/api_client.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_mismatch_doc_id_delete_targets_uses_compare_details():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    client.compare_adtrans = Mock(return_value={
        "success": True,
        "data": {
            "comparisons": [
                {
                    "emp_code": "G0010",
                    "gang_code": "G1H",
                    "category": "jabatan",
                    "adjustment_name": "AUTO TUNJANGAN JABATAN",
                    "status": "MISMATCH",
                    "source_amount": 150000,
                    "stored_amount": 100000,
                    "db_ptrj_doc_desc_details": [
                        {"doc_id": "ADAB126040123", "doc_desc": "(AL) TUNJANGAN JABATAN", "amount": 150000},
                        {"doc_id": "ADAB126040123", "doc_desc": "(AL) TUNJANGAN JABATAN", "amount": 150000},
                    ],
                },
                {
                    "emp_code": "G0020",
                    "category": "jabatan",
                    "adjustment_name": "AUTO TUNJANGAN JABATAN",
                    "status": "MATCH",
                    "db_ptrj_doc_desc_details": [{"doc_id": "MATCHDOC"}],
                },
            ]
        },
    })

    targets = client.get_mismatch_doc_id_delete_targets(4, 2026, "ab1", filters=["jabatan"], category_key="tunjangan_jabatan")

    client.compare_adtrans.assert_called_once_with(4, 2026, "AB1", filters=["jabatan"])
    assert [target.doc_id for target in targets] == ["ADAB126040123"]
    assert targets[0].action == "DELETE_RECORD"
    assert targets[0].emp_code == "G0010"
    assert targets[0].doc_desc == "(AL) TUNJANGAN JABATAN"
    assert targets[0].raw["source"] == "compare-adtrans"
```

- [ ] **Step 2: Run test to verify fail**

Run:

```powershell
pytest tests/test_api_models.py::test_get_mismatch_doc_id_delete_targets_uses_compare_details -q
```

Expected: fail because method does not exist.

- [ ] **Step 3: Implement minimal code**

Add `get_mismatch_doc_id_delete_targets(...)` to `ManualAdjustmentApiClient`:

```python
def get_mismatch_doc_id_delete_targets(
    self,
    period_month: int,
    period_year: int,
    division_code: str,
    filters: list[str] | None = None,
    category_key: str = "",
    gang_code: str | None = None,
    emp_code: str | None = None,
    adjustment_name: str | None = None,
) -> list[DuplicateDocIdTarget]:
    payload = self.compare_adtrans(period_month, period_year, division_code.strip().upper(), filters=filters)
    data = payload.get("data", {})
    comparisons = data.get("comparisons", []) if isinstance(data, dict) else []
    targets: list[DuplicateDocIdTarget] = []
    seen: set[str] = set()
    for comparison in comparisons if isinstance(comparisons, list) else []:
        if not isinstance(comparison, dict):
            continue
        if str(comparison.get("status") or "").upper().strip() != "MISMATCH":
            continue
        if emp_code and str(comparison.get("emp_code") or "").upper().strip() != emp_code.strip().upper():
            continue
        if gang_code and str(comparison.get("gang_code") or "").upper().strip() != gang_code.strip().upper():
            continue
        if adjustment_name and " ".join(str(comparison.get("adjustment_name") or "").upper().split()) != " ".join(adjustment_name.upper().split()):
            continue
        details = comparison.get("db_ptrj_doc_desc_details") or []
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            doc_id = str(detail.get("doc_id") or detail.get("docId") or detail.get("DocID") or "").strip()
            if not doc_id or doc_id.upper() in seen:
                continue
            seen.add(doc_id.upper())
            targets.append(DuplicateDocIdTarget(
                master_id="",
                doc_id=doc_id,
                doc_date="",
                emp_code=str(comparison.get("emp_code") or "").upper().strip(),
                emp_name="",
                doc_desc=str(detail.get("doc_desc") or comparison.get("adjustment_name") or "MISMATCH").strip(),
                amount=self._float_or_none(detail.get("amount")),
                action="DELETE_RECORD",
                keep_doc_id="",
                category=category_key,
                raw={"source": "compare-adtrans", "comparison": comparison, "detail": detail, "action": "DELETE_RECORD"},
            ))
    return targets
```

Add helper:

```python
def _float_or_none(self, value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

---

### Task 3: Wire Reset/Delete Source Mode

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests**

```python
def test_reset_docid_diff_request_marks_source_and_allows_gang_filter():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
    ])
    window = MainWindow(AppConfig(default_division_code="AB1"), registry, [DivisionOption("AB1", "Estate")])
    window.gang_code.setText("G1H")
    window.reset_docid_source.setCurrentText("DIFF/MISMATCH DocIDs")

    request = window._reset_docid_request()

    assert request["source_mode"] == "diff"
    assert request["gang_code"] == "G1H"
    window.close()
```

```python
def test_reset_fetch_worker_uses_compare_for_diff_source():
    client = Mock()
    client.get_mismatch_doc_id_delete_targets.return_value = []
    client.get_adtrans_doc_id_delete_targets.return_value = []
    worker = ResetDocIdFetchWorker(client, {
        "source_mode": "diff",
        "period_month": 4,
        "period_year": 2026,
        "division_code": "AB1",
        "filters": ["jabatan"],
        "category_key": "tunjangan_jabatan",
    })

    completed = []
    worker.completed.connect(completed.append)
    worker.run()

    client.get_mismatch_doc_id_delete_targets.assert_called_once()
    client.get_adtrans_doc_id_delete_targets.assert_not_called()
    assert completed == [[]]
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```powershell
pytest tests/test_api_models.py::test_reset_docid_diff_request_marks_source_and_allows_gang_filter tests/test_api_models.py::test_reset_fetch_worker_uses_compare_for_diff_source -q
```

Expected: fail because UI control and worker branch do not exist.

- [ ] **Step 3: Implement minimal code**

Add source combo in `_build_reset_docid_tab` with only the DIFF option:

```python
self.reset_docid_source = QComboBox()
self.reset_docid_source.addItem("DIFF/MISMATCH DocIDs", "diff")
form.addRow("Source", self.reset_docid_source)
```

Extend `_reset_docid_request`:

```python
"source_mode": str(self.reset_docid_source.currentData() or "diff"),
"gang_code": self.gang_code.text().strip().upper() or None,
```

Change gang block:

```python
if request["source_mode"] == "config" and self.gang_code.text().strip() and not self.emp_code.text().strip():
    ...
```

This branch remains only for internal compatibility. The visible UI uses the DIFF source, so the broad config source is not selectable by the operator.

Branch `ResetDocIdFetchWorker.run`:

```python
if self.request.get("source_mode") == "diff":
    self.completed.emit(self.client.get_mismatch_doc_id_delete_targets(**{
        key: value for key, value in self.request.items() if key != "source_mode" and value is not None
    }))
else:
    self.completed.emit(self.client.get_adtrans_doc_id_delete_targets(**{
        key: value for key, value in self.request.items() if key != "source_mode" and key != "gang_code" and value is not None
    }))
```

- [ ] **Step 4: Run tests to verify pass**

Run the same pytest command. Expected: pass.

---

### Task 4: Audit DIFF Deletes Back To MISS

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing test**

```python
def test_completed_actual_diff_reset_applies_sync_status_audit():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("tunjangan_jabatan", "Jabatan", "AUTO_BUFFER", ("JABATAN",), "jabatan"),
    ])
    window = MainWindow(AppConfig(default_division_code="AB1"), registry, [DivisionOption("AB1", "Estate")])
    window.category.setCurrentIndex(window.category.findData("tunjangan_jabatan"))
    window.reset_docid_source.setCurrentText("DIFF/MISMATCH DocIDs")
    window.reset_docid_dry_run.setChecked(False)
    client = Mock()
    client.sync_status.return_value = {"success": True, "data": {"updated_count": 1}}
    window._api_client = Mock(return_value=client)
    window.active_run_payload = RunPayload(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        gang_code=None,
        emp_code=None,
        adjustment_type="AUTO_BUFFER",
        adjustment_name="AUTO TUNJANGAN JABATAN",
        category_key="tunjangan_jabatan",
        runner_mode="mock",
        max_tabs=1,
        headless=True,
        only_missing_rows=True,
        row_limit=None,
        records=[],
        operation="delete_duplicates",
        duplicate_targets=[DuplicateDocIdTarget("", "ADAB1", "", "G0010", "", "JABATAN", 150000, "DELETE_RECORD", "", "tunjangan_jabatan", {"source": "compare-adtrans"})],
        delete_dry_run=False,
    )

    window._handle_run_completed({"success": True})

    client.sync_status.assert_called_once()
    kwargs = client.sync_status.call_args.kwargs
    assert kwargs["period_month"] == 4
    assert kwargs["period_year"] == 2026
    assert kwargs["division_code"] == "AB1"
    assert kwargs["adjustment_type"] == "AUTO_BUFFER"
    assert kwargs["adjustment_name"] == "AUTO TUNJANGAN JABATAN"
    assert kwargs["dry_run"] is False
    assert kwargs["only_if_adtrans_exists"] is True
    window.close()
```

- [ ] **Step 2: Run test to verify fail**

Run:

```powershell
pytest tests/test_api_models.py::test_completed_actual_diff_reset_applies_sync_status_audit -q
```

Expected: fail because no active payload or post-delete audit exists.

- [ ] **Step 3: Implement minimal code**

Add `self.active_run_payload: RunPayload | None = None` in `__init__`, set it in `start_runner`.

```python
self.active_run_payload = payload
```

Add helpers:

```python
def _payload_is_actual_diff_reset(self, payload: RunPayload | None) -> bool:
    if not payload or payload.operation != "delete_duplicates" or payload.delete_dry_run:
        return False
    return any((target.raw or {}).get("source") == "compare-adtrans" for target in payload.duplicate_targets or [])

def _sync_status_scope_for_category(self, category_key: str, payload: RunPayload) -> tuple[str | None, str | None]:
    if category_key == "spsi":
        return "AUTO_BUFFER", "AUTO SPSI"
    if category_key == "masa_kerja":
        return "AUTO_BUFFER", "AUTO MASA KERJA"
    if category_key == "tunjangan_jabatan":
        return "AUTO_BUFFER", "AUTO TUNJANGAN JABATAN"
    return payload.adjustment_type, payload.adjustment_name
```

Call after runner completion:

```python
if self._payload_is_actual_diff_reset(self.active_run_payload):
    self._apply_post_diff_reset_audit(self.active_run_payload)
```

Implement sync:

```python
def _apply_post_diff_reset_audit(self, payload: RunPayload) -> None:
    adjustment_type, adjustment_name = self._sync_status_scope_for_category(payload.category_key, payload)
    result = self._api_client().sync_status(
        period_month=payload.period_month,
        period_year=payload.period_year,
        division_code=payload.division_code,
        gang_code=payload.gang_code,
        emp_code=payload.emp_code,
        adjustment_type=adjustment_type,
        adjustment_name=adjustment_name,
        dry_run=False,
        only_if_adtrans_exists=True,
        updated_by="browser_automation",
    )
    data = result.get("data", {}) if isinstance(result, dict) else {}
    self.append_log(f"Post-delete sync-status audit applied: updated={data.get('updated_count', 0)}, skipped={data.get('skipped_count', 0)}.")
```

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

---

### Task 5: Make Division Sync Missing-Only

**Files:**
- Modify: `Auto Key In Refactor/app/ui/division_monitor.py`
- Modify: `Auto Key In Refactor/app/ui/division_run_dialog.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests**

Update existing sync-mode test or add:

```python
def test_division_monitor_sync_worker_uses_missing_only():
    client = Mock()
    client.sync_adtrans.return_value = {"success": True, "data": {"synced_count": 1}}
    worker = SyncWorker(client, 4, 2026, "AB1", ["jabatan"])
    completed = []
    worker.completed.connect(completed.append)

    worker.run()

    client.sync_adtrans.assert_called_once_with(4, 2026, "AB1", filters=["jabatan"], sync_mode="MISSING_ONLY")
```

Patch the standalone dialog sync test:

```python
def test_division_run_dialog_sync_missing_uses_missing_only():
    QApplication.instance() or QApplication([])
    client = Mock()
    client.sync_adtrans.return_value = {"success": True, "data": {"synced_count": 1, "skipped_match": 0}}
    dialog = DivisionRunDialog(AppConfig(default_division_code="AB1"), CategoryRegistry([
        AdjustmentCategory("tunjangan_jabatan", "Jabatan", "AUTO_BUFFER", ("JABATAN",), "jabatan"),
    ]), client, "AB1", "Estate", "tunjangan_jabatan", "Jabatan", "dry_run", 4, 2026)

    dialog._on_sync_missing()

    client.sync_adtrans.assert_called_once_with(4, 2026, "AB1", filters=["jabatan"], sync_mode="MISSING_ONLY")
    dialog.close()
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```powershell
pytest tests/test_api_models.py::test_division_monitor_sync_worker_uses_missing_only tests/test_api_models.py::test_division_run_dialog_sync_missing_uses_missing_only -q
```

Expected: fail because both call `MISMATCH_AND_MISSING`.

- [ ] **Step 3: Implement minimal code**

Change both calls:

```python
sync_mode="MISSING_ONLY"
```

Update UI copy from `Sync Missing` to `Sync Missing Only` where applicable.

- [ ] **Step 4: Run tests to verify pass**

Run the same pytest command. Expected: pass.

---

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `Auto Key In Refactor/README.md`
- Test: existing focused pytest suite

- [ ] **Step 1: Update README**

In Reset/Delete DocID section, state:

```markdown
- Reset/delete di tab ini hanya memakai source **DIFF/MISMATCH DocIDs**.
- Mode **DIFF/MISMATCH DocIDs** memakai `compare-adtrans/by-api-key`, hanya mengambil `status=MISMATCH`, lalu memakai `db_ptrj_doc_desc_details[].doc_id` sebagai target delete.
- Setelah delete aktual, app menjalankan `sync-status/by-api-key` untuk audit ulang supaya row yang sudah dihapus berubah menjadi `sync:MISS | match:MISMATCH`.
```

In Process section, state:

```markdown
- Checkbox **Input MISS only** tidak memasukkan `DIFF`/`MISMATCH`. Data DIFF harus dihapus/reset dulu dari tab Reset/Delete DocID.
```

- [ ] **Step 2: Run focused tests**

Run:

```powershell
pytest tests/test_api_models.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run syntax/type smoke checks**

Run:

```powershell
python -m compileall app
```

Expected: compile succeeds.

- [ ] **Step 4: Commit**

```powershell
git add 'Auto Key In Refactor/app/core/api_client.py' 'Auto Key In Refactor/app/ui/main_window.py' 'Auto Key In Refactor/app/ui/division_monitor.py' 'Auto Key In Refactor/app/ui/division_run_dialog.py' 'Auto Key In Refactor/tests/test_api_models.py' 'Auto Key In Refactor/README.md' 'Auto Key In Refactor/docs/superpowers/plans/2026-05-03-miss-only-diff-reset.md'
git commit -m "fix: separate miss input from diff reset"
```

---

## Self-Review

- Spec coverage: MISS-only filtering, compare-based DocID extraction, post-delete audit, and missing-only sync are each covered by a task.
- Placeholder scan: no `TBD`, `TODO`, `implement later`, or unresolved placeholders.
- Type consistency: new methods use existing `DuplicateDocIdTarget`, `RunPayload`, and `ManualAdjustmentApiClient` patterns.
