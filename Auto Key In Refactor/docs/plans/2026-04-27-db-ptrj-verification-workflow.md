# db_ptrj Verification Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add automatic and manual db_ptrj verification so rows can be green when agent input is done, while a separate DB status confirms whether the data exists in db_ptrj.

**Architecture:** Keep runner events as the source of input-form progress, and add UI-side db_ptrj verification state as a separate concern. Pre-run verification checks period + emp_code + category filter directly against db_ptrj, skips rows that already have any actual value, and warns when existing amount differs. Post-run verification runs after all tabs submit and updates DB status for rows that were input.

**Tech Stack:** Python 3, PySide6 desktop UI, existing `ManualAdjustmentApiClient.check_adtrans`, TypeScript Playwright runner event stream, pytest.

---

### Task 1: Extract db_ptrj verification decision logic

**Files:**
- Modify: `Auto Key In Refactor/app/core/run_service.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing tests**

Add these tests to `tests/test_api_models.py` near the existing run service tests:

```python
from app.core.run_service import DbVerificationDecision, evaluate_db_ptrj_status


def test_evaluate_db_ptrj_status_marks_missing_when_actual_is_zero():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=0)
    assert decision == DbVerificationDecision("Missing in DB", False, "")


def test_evaluate_db_ptrj_status_marks_already_in_db_when_amount_matches():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=4000)
    assert decision == DbVerificationDecision("Already in DB", True, "already exists in db_ptrj; skipped automatically")


def test_evaluate_db_ptrj_status_marks_mismatch_and_skips():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=3000)
    assert decision == DbVerificationDecision("DB Mismatch", True, "db_ptrj amount 3000 differs from expected 4000; skipped automatically")
```

**Step 2: Run tests to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_evaluate_db_ptrj_status_marks_missing_when_actual_is_zero tests/test_api_models.py::test_evaluate_db_ptrj_status_marks_already_in_db_when_amount_matches tests/test_api_models.py::test_evaluate_db_ptrj_status_marks_mismatch_and_skips -v
```

Expected: FAIL because `DbVerificationDecision` and `evaluate_db_ptrj_status` do not exist.

**Step 3: Implement minimal logic**

Add to `app/core/run_service.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DbVerificationDecision:
    status: str
    skip_input: bool
    warning: str


def _format_amount(value: float) -> str:
    return f"{value:g}"


def evaluate_db_ptrj_status(expected_amount: float, actual_amount: float) -> DbVerificationDecision:
    if actual_amount == 0:
        return DbVerificationDecision("Missing in DB", False, "")
    if actual_amount == expected_amount:
        return DbVerificationDecision("Already in DB", True, "already exists in db_ptrj; skipped automatically")
    return DbVerificationDecision(
        "DB Mismatch",
        True,
        f"db_ptrj amount {_format_amount(actual_amount)} differs from expected {_format_amount(expected_amount)}; skipped automatically",
    )
```

**Step 4: Run tests to verify pass**

Run the same pytest command.

Expected: PASS.

**Step 5: Commit**

```bash
git add "Auto Key In Refactor/app/core/run_service.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: add db_ptrj verification decisions"
```

---

### Task 2: Add separate DB status state to the records table

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test**

Add a UI test:

```python
def test_records_table_tracks_input_and_db_status_separately(qtbot):
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    qtbot.addWidget(window)
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")

    window.set_records([record])

    assert window.records_table.horizontalHeaderItem(0).text() == "Input Status"
    assert window.records_table.horizontalHeaderItem(1).text() == "DB Status"
    assert window.records_table.item(0, 0).text() == "Pending"
    assert window.records_table.item(0, 1).text() == "Not Checked"
    window.close()
```

If `qtbot` is not available because pytest-qt is not installed, use the existing QApplication pattern without `qtbot` and close the window manually.

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_records_table_tracks_input_and_db_status_separately -v
```

Expected: FAIL because the records table still uses a single status column.

**Step 3: Update table headers and status state**

In `MainWindow._build_process_tab`, change the records table headers from the current first status columns to include:

```python
[
    "Input Status",
    "DB Status",
    "API Sync",
    "API Match",
    "Emp Code",
    "Gang",
    "Division",
    "Adjustment",
    "Description",
    "ADCode",
    "Remarks ADCode",
    "Amount",
    "Remarks",
]
```

In `set_records`, initialize `record_status` with both statuses:

```python
self.record_status[key] = {"row": row, "input_status": "Pending", "db_status": "Not Checked", "message": ""}
values = [
    "Pending",
    "Not Checked",
    self._sync_status_from_remarks(record),
    self._match_status_from_remarks(record),
    record.emp_code,
    record.gang_code,
    record.division_code,
    record.adjustment_name,
    self._description_for_record(record),
    self._adcode_for_record(record),
    self._remarks_adcode(record),
    f"{record.amount:g}",
    record.remarks,
]
```

Update `_reset_record_status`, `_update_record_from_event`, and `_refresh_summary` to read/write `input_status` instead of `status`.

**Step 4: Run test to verify pass**

Run the same pytest command.

Expected: PASS.

**Step 5: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: separate input and db row statuses"
```

---

### Task 3: Color rows based on input status and DB status

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test**

Add:

```python
def test_row_success_marks_input_done_green():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([record])

    window._update_record_from_event("row.success", {"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "tab_index": 0}, "row add confirmed")

    assert window.records_table.item(0, 0).text() == "Input Done"
    assert window.record_status[window._record_key(record)]["input_status"] == "Input Done"
    window.close()
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_row_success_marks_input_done_green -v
```

Expected: FAIL because `row.success` still writes `Success`.

**Step 3: Implement status mapping and row color helper**

In `_update_record_from_event`, use:

```python
status_map = {
    "row.started": "Running",
    "row.success": "Input Done",
    "row.skipped": "Skipped",
    "row.failed": "Failed",
}
```

Add helper:

```python
def _apply_record_row_style(self, row: int, input_status: str, db_status: str) -> None:
    if input_status == "Input Done":
        background = Qt.GlobalColor.darkGreen
        foreground = Qt.GlobalColor.white
    elif input_status == "Skipped":
        background = Qt.GlobalColor.darkCyan
        foreground = Qt.GlobalColor.white
    elif input_status == "Failed" or db_status == "DB Mismatch":
        background = Qt.GlobalColor.darkRed
        foreground = Qt.GlobalColor.white
    elif db_status == "Already in DB":
        background = Qt.GlobalColor.darkBlue
        foreground = Qt.GlobalColor.white
    else:
        return
    for column in range(self.records_table.columnCount()):
        item = self.records_table.item(row, column)
        if item:
            item.setBackground(background)
            item.setForeground(foreground)
```

Call it after status updates and after setting each row in `set_records`.

**Step 4: Run test and full suite**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: highlight input and db row states"
```

---

### Task 4: Add pre-run db_ptrj verification button and skip warnings

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test for applying verification results**

Add:

```python
def test_apply_precheck_skips_rows_already_in_db():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([record])

    window._apply_db_ptrj_results([{"emp_code": "B0065", "spsi": 4000}], precheck=True)

    state = window.record_status[window._record_key(record)]
    assert state["input_status"] == "Skipped"
    assert state["db_status"] == "Already in DB"
    assert "skipped automatically" in state["message"]
    window.close()
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_apply_precheck_skips_rows_already_in_db -v
```

Expected: FAIL because `_apply_db_ptrj_results` does not exist.

**Step 3: Implement `_apply_db_ptrj_results`**

Import the new decision helper:

```python
from app.core.run_service import apply_row_limit, filter_by_category, evaluate_db_ptrj_status
```

Add method:

```python
def _db_actual_by_emp_filter(self, data: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    filters = {self._filter_for_record(record) for record in self.records}
    actual: dict[tuple[str, str], float] = {}
    for item in data:
        emp_code = str(item.get("emp_code") or item.get("EmpCode") or "").upper().strip()
        for filter_name in filters:
            actual[(emp_code, filter_name)] = float(item.get(filter_name, 0) or 0)
    return actual


def _apply_db_ptrj_results(self, data: list[dict[str, Any]], precheck: bool) -> None:
    actual = self._db_actual_by_emp_filter(data)
    for record in self.records:
        key = self._record_key(record)
        state = self.record_status.get(key, {})
        row = int(state.get("row", -1))
        filter_name = self._filter_for_record(record)
        decision = evaluate_db_ptrj_status(record.amount, actual.get((record.emp_code, filter_name), 0.0))
        if precheck:
            if decision.skip_input:
                state["input_status"] = "Skipped"
                state["message"] = decision.warning
                self.append_log(f"{record.emp_code} {record.adjustment_name}: {decision.warning}")
            state["db_status"] = decision.status
        else:
            state["db_status"] = "DB Match" if decision.status == "Already in DB" else decision.status
        if row >= 0:
            self.records_table.setItem(row, 0, QTableWidgetItem(str(state.get("input_status", "Pending"))))
            self.records_table.setItem(row, 1, QTableWidgetItem(str(state.get("db_status", "Not Checked"))))
            self._apply_record_row_style(row, str(state.get("input_status", "")), str(state.get("db_status", "")))
    self._refresh_summary()
```

**Step 4: Add button**

In `_build_process_tab`, add button beside fetch/run controls:

```python
self.precheck_db_button = QPushButton("Verify db_ptrj Before Run")
self.precheck_db_button.clicked.connect(self.verify_db_ptrj_before_run)
```

Implement:

```python
def verify_db_ptrj_before_run(self) -> None:
    self._start_db_ptrj_check(precheck=True)
```

Refactor `check_db_ptrj` to call `_start_db_ptrj_check(precheck=False)` for manual verification.

**Step 5: Run tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: add pre-run db_ptrj verification"
```

---

### Task 5: Filter skipped rows out of runner payload

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test**

Add:

```python
def test_runner_records_exclude_precheck_skipped_rows():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    existing = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    missing = normalize_record({"emp_code": "B0070", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([existing, missing])
    window._apply_db_ptrj_results([{"emp_code": "B0065", "spsi": 4000}, {"emp_code": "B0070", "spsi": 0}], precheck=True)

    runnable = window._records_for_runner()

    assert [record.emp_code for record in runnable] == ["B0070"]
    window.close()
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_runner_records_exclude_precheck_skipped_rows -v
```

Expected: FAIL because `_records_for_runner` does not exist or still returns all records.

**Step 3: Implement `_records_for_runner` and use it in run payload**

Add:

```python
def _records_for_runner(self) -> list[ManualAdjustmentRecord]:
    runnable = []
    for record in self.records:
        state = self.record_status.get(self._record_key(record), {})
        if state.get("input_status") == "Skipped" and state.get("db_status") in {"Already in DB", "DB Mismatch"}:
            continue
        runnable.append(record)
    return runnable
```

In the run-start method that builds `RunPayload`, replace direct use of `self.records` with `self._records_for_runner()` after category and row-limit filtering. If no runnable rows remain, do not start the runner; set context label/log to `All rows skipped because db_ptrj already has data or mismatched amounts.`

**Step 4: Run tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: skip db_ptrj existing rows during run"
```

---

### Task 6: Run automatic post-submit db_ptrj verification

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test**

Add:

```python
def test_run_completed_starts_postcheck_for_successful_rows(monkeypatch):
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([record])
    window._update_record_from_event("row.success", {"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "tab_index": 0}, "row add confirmed")
    called = {}
    monkeypatch.setattr(window, "_start_db_ptrj_check", lambda precheck: called.setdefault("precheck", precheck))

    window._handle_run_completed({"success": True})

    assert called == {"precheck": False}
    window.close()
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_run_completed_starts_postcheck_for_successful_rows -v
```

Expected: FAIL because `_handle_run_completed` only switches to the verify tab and does not start automatic verification.

**Step 3: Trigger post-check after successful run**

In `_handle_run_completed`, after `self.use_last_run_employees()` and before/after switching tabs, add:

```python
if self.last_successful_records:
    self._start_db_ptrj_check(precheck=False)
```

Ensure `_start_db_ptrj_check(precheck=False)` sets rows with `Input Done` to DB status `Checking` before the worker starts.

**Step 4: Update completion handler**

Modify `_handle_verify_completed` so it knows whether the current check is precheck or postcheck. Add a field like `self.verify_precheck_mode: bool = False`. On completion:

```python
self._apply_db_ptrj_results(data, precheck=self.verify_precheck_mode)
self._render_verify_results(data)
```

**Step 5: Run tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: auto verify db_ptrj after submit"
```

---

### Task 7: Update summary counts for input done and DB verified rows

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

**Step 1: Write failing test**

Add:

```python
def test_summary_separates_input_done_and_db_match():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([record])
    window._update_record_from_event("row.success", {"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "tab_index": 0}, "row add confirmed")
    window._apply_db_ptrj_results([{"emp_code": "B0065", "spsi": 4000}], precheck=False)

    assert window.summary_success.text() == "1"
    assert window.summary_db_match.text() == "1"
    window.close()
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_summary_separates_input_done_and_db_match -v
```

Expected: FAIL because `summary_db_match` does not exist.

**Step 3: Add summary label**

In summary UI construction, add label:

```python
self.summary_db_match = QLabel("0")
```

Add it to the summary cards as `("DB Match", self.summary_db_match)`.

Update `_refresh_summary`:

```python
db_match_count = 0
for record in self.records:
    state = self.record_status.get(self._record_key(record), {})
    input_status = str(state.get("input_status", "Pending"))
    db_status = str(state.get("db_status", "Not Checked"))
    if input_status == "Input Done":
        success_records.append(record)
    if db_status == "DB Match":
        db_match_count += 1
...
self.summary_db_match.setText(str(db_match_count))
```

Update the summary table to include both input and DB status columns.

**Step 4: Run tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: summarize db_ptrj verification status"
```

---

### Task 8: Manual validation with runner modes

**Files:**
- No code changes unless validation finds a bug.

**Step 1: Build runner**

Run:

```bash
npm --prefix runner run build
```

Expected: TypeScript build succeeds.

**Step 2: Run Python tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -v
```

Expected: all tests pass.

**Step 3: Launch desktop app**

Run:

```bash
python -m app
```

Expected: app opens.

**Step 4: Validate pre-check manually**

Use a period/category with known db_ptrj data. Click `Verify db_ptrj Before Run`.

Expected:
- Rows already in db_ptrj become `Input Status = Skipped`.
- Matching rows become `DB Status = Already in DB`.
- Different amount rows become `DB Status = DB Mismatch`.
- Missing rows remain `Input Status = Pending`, `DB Status = Missing in DB`.
- Log contains warning for each skipped row.

**Step 5: Validate run filtering**

Start Auto Key In.

Expected:
- Runner only receives missing rows.
- Skipped rows are not sent to any tab/agent.
- `row.success` rows become green with `Input Status = Input Done`.

**Step 6: Validate post-check**

Wait until all tabs submit.

Expected:
- App automatically checks db_ptrj.
- Rows that entered db_ptrj become `DB Status = DB Match`.
- Summary shows separate input-done and DB-match counts.
- Manual `Check db_ptrj` still works as a fallback.

**Step 7: Commit validation fixes if needed**

```bash
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py" "Auto Key In Refactor/app/core/run_service.py"
git commit -m "fix: finalize db_ptrj verification workflow"
```
