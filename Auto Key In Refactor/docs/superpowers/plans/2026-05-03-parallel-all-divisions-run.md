# Parallel All Divisions Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-parallel "Run All Divisions" mode where each division gets one independent runner/browser window with 5 tabs and can process a selected category with either one adjustment name or all adjustment names.

**Architecture:** Keep the existing single-division flow intact. Add focused helper methods and a batch orchestration layer inside `MainWindow`, keyed by division code, while reusing `ManualAdjustmentQuery`, `FetchWorker`, `RunPayload`, `RunWorker`, `RunnerBridge`, and the existing session scan. Extract the record preparation rules into pure helpers so single-run and batch-run use the same category, division guard, and MISS/retry-safe filtering behavior.

**Tech Stack:** Python 3.11, PySide6, pytest, existing TypeScript Playwright runner via `RunnerBridge`.

---

### Task 1: Extract Shared Record Preparation

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests for shared filtering**

Add these imports near the existing `app.ui.main_window` import block in `Auto Key In Refactor/tests/test_api_models.py`:

```python
from app.ui.main_window import PreparedRunRecords, prepare_records_for_run, record_is_miss_for_run
```

If the import block already imports names from `app.ui.main_window`, merge the new names into that import instead of creating a duplicate import.

Add these tests near the existing fetch/retry-safe tests:

```python
def test_prepare_records_for_run_applies_category_division_and_row_limit():
    records = [
        normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi"),
        normalize_record({"emp_code": "C0001", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi"),
        normalize_record({"emp_code": "B0077", "adjustment_name": "PREMI TBS", "adjustment_type": "PREMI", "amount": 100000}, "premi"),
    ]

    prepared = prepare_records_for_run(
        records,
        category_key="spsi",
        division_code="P1B",
        row_limit=1,
        miss_only=False,
        verification={},
    )

    assert isinstance(prepared, PreparedRunRecords)
    assert [record.emp_code for record in prepared.records] == ["B0065"]
    assert prepared.raw_count == 3
    assert prepared.category_count_after_division_guard == 1
    assert [record.emp_code for record in prepared.division_rejected_records] == ["C0001"]


def test_record_is_miss_for_run_uses_premium_retry_keys_when_verified():
    record = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
        "transaction_index": 1,
    }, "premi")

    assert record_is_miss_for_run(
        record,
        verification={"source": "sync-status"},
        premium_retry_record_keys={record.record_key},
    ) is True
    assert record_is_miss_for_run(
        record,
        verification={"source": "sync-status"},
        premium_retry_record_keys=set(),
    ) is False
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run from `Auto Key In Refactor`:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_prepare_records_for_run_applies_category_division_and_row_limit tests/test_api_models.py::test_record_is_miss_for_run_uses_premium_retry_keys_when_verified -q
```

Expected: FAIL because `PreparedRunRecords`, `prepare_records_for_run`, or `record_is_miss_for_run` does not exist.

- [ ] **Step 3: Add the shared helper code**

In `Auto Key In Refactor/app/ui/main_window.py`, add `dataclass` to the imports:

```python
from dataclasses import dataclass
```

Place this code after `FetchVerificationStatus = dict[tuple[str, str], dict[str, Any]]` and before the category constant definitions:

```python
@dataclass(frozen=True)
class PreparedRunRecords:
    records: list[ManualAdjustmentRecord]
    raw_count: int
    category_count_after_division_guard: int
    division_rejected_records: list[ManualAdjustmentRecord]
    premium_retry_record_keys: set[str]
    premium_retry_held_groups: dict[Any, str]
    miss_filter_applied: bool
```

Place these helper functions near `build_premium_retry_plan_from_sync_status`:

```python
def fetch_verification_display_for_record(
    record: ManualAdjustmentRecord,
    verification: FetchVerificationStatus,
) -> str:
    status = verification.get((record.emp_code, filter_for_record(record)), {})
    return str(status.get("status") or "") if isinstance(status, dict) else ""


def record_is_miss_for_run(
    record: ManualAdjustmentRecord,
    verification: FetchVerificationStatus,
    premium_retry_record_keys: set[str],
) -> bool:
    if record.category_key in PREMI_CATEGORY_KEYS and verification:
        return record.record_key in premium_retry_record_keys
    verified_status = fetch_verification_display_for_record(record, verification).upper()
    if verified_status in {"VERIFIED_MATCH", "VERIFIED_MISMATCH"}:
        return False
    if verified_status == "VERIFIED_NOT_FOUND":
        return True
    return record_is_stale_miss(record)


def prepare_records_for_run(
    records: list[ManualAdjustmentRecord],
    category_key: str,
    division_code: str,
    row_limit: int | None,
    miss_only: bool,
    verification: FetchVerificationStatus,
) -> PreparedRunRecords:
    filtered_records = filter_by_category(records, category_key)
    filtered_records, division_rejected_records = filter_records_by_division_prefix(filtered_records, division_code)
    category_count_after_division_guard = len(filtered_records)
    premium_retry_record_keys: set[str] = set()
    premium_retry_held_groups: dict[Any, str] = {}
    miss_filter_applied = False
    premium_preview = category_key in PREMI_CATEGORY_KEYS
    manual_preview = category_key in MANUAL_PREVIEW_CATEGORY_KEYS

    if premium_preview and verification:
        if verification.get("source") == "sync-status":
            premium_retry_record_keys = set(verification.get("retry_record_keys", set()))
            premium_retry_held_groups = dict(verification.get("held_groups", {}))
        else:
            premium_retry_record_keys, premium_retry_held_groups = build_premium_retry_plan(filtered_records, verification)

    if miss_only and premium_preview and verification:
        filtered_records = [
            record for record in filtered_records
            if record_is_miss_for_run(record, verification, premium_retry_record_keys)
        ]
        miss_filter_applied = True
    elif miss_only and not manual_preview:
        filtered_records = [
            record for record in filtered_records
            if record_is_miss_for_run(record, verification, premium_retry_record_keys)
        ]
        miss_filter_applied = True

    return PreparedRunRecords(
        records=apply_row_limit(filtered_records, row_limit),
        raw_count=len(records),
        category_count_after_division_guard=category_count_after_division_guard,
        division_rejected_records=division_rejected_records,
        premium_retry_record_keys=premium_retry_record_keys,
        premium_retry_held_groups=premium_retry_held_groups,
        miss_filter_applied=miss_filter_applied,
    )
```

Update `MainWindow._fetch_verification_display` to delegate:

```python
    def _fetch_verification_display(self, record: ManualAdjustmentRecord) -> str:
        return fetch_verification_display_for_record(record, self.fetch_verification_status)
```

Update `MainWindow._record_is_miss` to delegate:

```python
    def _record_is_miss(self, record: ManualAdjustmentRecord) -> bool:
        return record_is_miss_for_run(record, self.fetch_verification_status, self.premium_retry_record_keys)
```

Refactor `_handle_fetch_completed` so it calls `prepare_records_for_run(...)` once after logging verification results:

```python
        category_key = str(self.category.currentData() or "")
        row_limit = self.row_limit.value() or None
        prepared = prepare_records_for_run(
            records,
            category_key,
            self._selected_division_code(),
            row_limit,
            self.process_only_miss.isChecked(),
            self.fetch_verification_status,
        )
        filtered_records = prepared.records
        division_rejected_records = prepared.division_rejected_records
        category_count_after_division_guard = prepared.category_count_after_division_guard
        self.premium_retry_record_keys = prepared.premium_retry_record_keys
        self.premium_retry_held_groups = prepared.premium_retry_held_groups
        miss_filter_applied = prepared.miss_filter_applied
```

Keep the existing user-facing log messages after that assignment block, but remove the old duplicated filtering and retry-plan code.

- [ ] **Step 4: Run the focused tests**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_prepare_records_for_run_applies_category_division_and_row_limit tests/test_api_models.py::test_record_is_miss_for_run_uses_premium_retry_keys_when_verified -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "refactor: share run record preparation"
```

### Task 2: Add Batch Job and Payload Helpers

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests for ALL adjustment name and per-division payloads**

Add these tests near `test_selected_jobs_create_payloads_from_saved_config`:

```python
def test_batch_adjustment_name_all_is_omitted_from_query_and_payload():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi")])
    window = MainWindow(config, registry, [DivisionOption("AB1", "AB1")])
    window.category.setCurrentIndex(0)
    window.adjustment_type.setCurrentText("PREMI")
    window.adjustment_name.setText("ALL")

    jobs = window.build_all_division_jobs()
    payload = window.build_payload_from_all_division_job(jobs[0], [])
    query = window.build_query_from_all_division_job(jobs[0])

    assert jobs[0]["adjustment_name"] is None
    assert payload.adjustment_name is None
    assert "adjustment_name" not in query.params()
    window.close()


def test_build_all_division_jobs_uses_every_configured_division_with_five_tabs():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    window = MainWindow(config, registry, [
        DivisionOption("AB1", "Air Ruak B1"),
        DivisionOption("P1B", "Parit Gunung 1B"),
    ])
    window.category.setCurrentIndex(0)
    window.adjustment_type.setCurrentText("AUTO_BUFFER")
    window.adjustment_name.setText("AUTO SPSI")
    window.runner_mode.setCurrentText("multi_tab_shared_session")
    window.max_tabs.setValue(2)

    jobs = window.build_all_division_jobs()
    payloads = [window.build_payload_from_all_division_job(job, []) for job in jobs]

    assert [job["division_code"] for job in jobs] == ["AB1", "P1B"]
    assert [payload.division_code for payload in payloads] == ["AB1", "P1B"]
    assert [payload.max_tabs for payload in payloads] == [5, 5]
    assert [payload.adjustment_name for payload in payloads] == ["AUTO SPSI", "AUTO SPSI"]
    window.close()
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_batch_adjustment_name_all_is_omitted_from_query_and_payload tests/test_api_models.py::test_build_all_division_jobs_uses_every_configured_division_with_five_tabs -q
```

Expected: FAIL because `build_all_division_jobs`, `build_payload_from_all_division_job`, or `build_query_from_all_division_job` does not exist.

- [ ] **Step 3: Add helper state and builder methods**

In `MainWindow.__init__`, after `self.jobs`, add:

```python
        self.all_division_jobs: dict[str, dict[str, Any]] = {}
        self.all_division_fetch_threads: dict[str, QThread] = {}
        self.all_division_fetch_workers: dict[str, FetchWorker] = {}
        self.all_division_run_threads: dict[str, QThread] = {}
        self.all_division_run_workers: dict[str, RunWorker] = {}
        self.all_division_bridges: dict[str, RunnerBridge] = {}
        self.all_division_artifacts: dict[str, RunArtifactPaths] = {}
```

Add these methods near `build_payload_from_job`:

```python
    def _all_division_codes(self) -> list[str]:
        options = self.divisions or [DivisionOption(self.config.default_division_code, self.config.default_division_code)]
        return [division.code.strip().upper() for division in options if division.code.strip()]

    def _batch_adjustment_name(self) -> str | None:
        value = self.adjustment_name.text().strip()
        return None if not value or value.upper() == "ALL" else value

    def build_all_division_jobs(self) -> list[dict[str, Any]]:
        category_key = str(self.category.currentData() or "")
        jobs: list[dict[str, Any]] = []
        for division_code in self._all_division_codes():
            jobs.append({
                "period_month": self.period_month.value(),
                "period_year": self.period_year.value(),
                "division_code": division_code,
                "gang_code": self.gang_code.text().strip().upper(),
                "emp_code": self.emp_code.text().strip().upper(),
                "adjustment_type": self.adjustment_type.currentText().strip().upper(),
                "adjustment_name": self._batch_adjustment_name(),
                "category_key": category_key,
                "runner_mode": self.runner_mode.currentText(),
                "max_tabs": 5,
                "headless": self.headless.isChecked(),
                "only_missing_rows": self.only_missing.isChecked(),
                "row_limit": self.row_limit.value() or None,
                "status": "Pending",
                "records_total": 0,
                "success_count": 0,
                "failed_count": 0,
                "message": "",
            })
        return jobs

    def build_query_from_all_division_job(self, job: dict[str, Any]) -> ManualAdjustmentQuery:
        return ManualAdjustmentQuery(
            period_month=int(job["period_month"]),
            period_year=int(job["period_year"]),
            division_code=str(job["division_code"]).strip().upper() or None,
            gang_code=str(job.get("gang_code") or "").strip().upper() or None,
            emp_code=str(job.get("emp_code") or "").strip().upper() or None,
            adjustment_type=str(job.get("adjustment_type") or "").strip().upper() or None,
            adjustment_name=str(job.get("adjustment_name") or "").strip() or None,
        )

    def build_payload_from_all_division_job(
        self,
        job: dict[str, Any],
        records: list[ManualAdjustmentRecord],
    ) -> RunPayload:
        return RunPayload(
            period_month=int(job["period_month"]),
            period_year=int(job["period_year"]),
            division_code=str(job["division_code"]).strip().upper(),
            gang_code=str(job.get("gang_code") or "").strip().upper() or None,
            emp_code=str(job.get("emp_code") or "").strip().upper() or None,
            adjustment_type=str(job.get("adjustment_type") or "").strip().upper() or None,
            adjustment_name=str(job.get("adjustment_name") or "").strip() or None,
            category_key=str(job.get("category_key") or ""),
            runner_mode=str(job.get("runner_mode") or "multi_tab_shared_session"),
            max_tabs=5,
            headless=bool(job.get("headless")),
            only_missing_rows=bool(job.get("only_missing_rows")),
            row_limit=job.get("row_limit"),
            records=records,
        )
```

- [ ] **Step 4: Run the focused tests**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_batch_adjustment_name_all_is_omitted_from_query_and_payload tests/test_api_models.py::test_build_all_division_jobs_uses_every_configured_division_with_five_tabs -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: build all-division run jobs"
```

### Task 3: Add Batch UI and Session Preflight

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing tests for batch controls and preflight**

Add these tests near the batch job helper tests:

```python
def test_process_tab_has_run_all_divisions_button_and_batch_table():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("AB1", "AB1")])

    assert window.run_all_divisions_button.text() == "Run All Divisions"
    assert window.stop_all_divisions_button.text() == "Stop All Divisions"
    assert window.all_division_status_table.horizontalHeaderItem(0).text() == "Division"
    window.close()


def test_all_division_session_preflight_blocks_missing_session(tmp_path):
    config = AppConfig(
        runner_command=f"node {tmp_path / 'runner' / 'dist' / 'cli.js'}",
        default_division_code="AB1",
    )
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi")])
    window = MainWindow(config, registry, [DivisionOption("AB1", "AB1"), DivisionOption("P1B", "P1B")])
    window.runner_mode.setCurrentText("multi_tab_shared_session")

    jobs = window.build_all_division_jobs()

    assert window.missing_sessions_for_all_division_jobs(jobs) == ["AB1", "P1B"]
    window.runner_mode.setCurrentText("dry_run")
    dry_jobs = window.build_all_division_jobs()
    assert window.missing_sessions_for_all_division_jobs(dry_jobs) == []
    window.close()
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_process_tab_has_run_all_divisions_button_and_batch_table tests/test_api_models.py::test_all_division_session_preflight_blocks_missing_session -q
```

Expected: FAIL because UI fields or preflight method does not exist.

- [ ] **Step 3: Add UI controls and render method**

In `_build_process_tab`, after the existing controls row is added and before `job_group`, add:

```python
        batch_controls = QHBoxLayout()
        batch_controls.setSpacing(10)
        self.run_all_divisions_button = QPushButton("Run All Divisions")
        self.run_all_divisions_button.setObjectName("success")
        self.stop_all_divisions_button = QPushButton("Stop All Divisions")
        self.stop_all_divisions_button.setObjectName("danger")
        self.stop_all_divisions_button.setEnabled(False)
        self.run_all_divisions_button.clicked.connect(self.run_all_divisions)
        self.stop_all_divisions_button.clicked.connect(self.stop_all_division_runs)
        batch_controls.addWidget(self.run_all_divisions_button)
        batch_controls.addWidget(self.stop_all_divisions_button)
        batch_controls.addStretch(1)
        layout.addLayout(batch_controls)

        all_division_group = QGroupBox("All Division Run Status")
        all_division_layout = QVBoxLayout(all_division_group)
        self.all_division_status_table = QTableWidget(0, 6)
        self.all_division_status_table.setHorizontalHeaderLabels(["Division", "Status", "Records", "Success", "Failed", "Message"])
        self.all_division_status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.all_division_status_table.setMaximumHeight(180)
        all_division_layout.addWidget(self.all_division_status_table)
        layout.addWidget(all_division_group)
```

Add these methods near `_render_jobs`:

```python
    def render_all_division_jobs(self) -> None:
        jobs = list(self.all_division_jobs.values())
        self.all_division_status_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = [
                str(job.get("division_code", "")),
                str(job.get("status", "Pending")),
                str(job.get("records_total", 0)),
                str(job.get("success_count", 0)),
                str(job.get("failed_count", 0)),
                str(job.get("message", "")),
            ]
            for column, value in enumerate(values):
                self.all_division_status_table.setItem(row, column, QTableWidgetItem(value))

    def _set_all_division_buttons_enabled(self, running: bool) -> None:
        self.run_all_divisions_button.setEnabled(not running)
        self.stop_all_divisions_button.setEnabled(running)

    def _session_required_for_mode(self, mode: str) -> bool:
        return mode not in {"dry_run", "mock", "fresh_login_single"}

    def missing_sessions_for_all_division_jobs(self, jobs: list[dict[str, Any]]) -> list[str]:
        if not any(self._session_required_for_mode(str(job.get("runner_mode") or "")) for job in jobs):
            return []
        active_by_code = {
            str(item["code"]).upper(): bool(item["active"])
            for item in self._scan_session_status()
        }
        missing: list[str] = []
        for job in jobs:
            division_code = str(job.get("division_code") or "").strip().upper()
            if division_code and not active_by_code.get(division_code, False):
                missing.append(division_code)
        return missing
```

Update `_set_run_buttons_enabled` to include the batch controls:

```python
        if hasattr(self, "run_all_divisions_button"):
            self.run_all_divisions_button.setEnabled(enabled and not self._all_division_is_active())
        if hasattr(self, "stop_all_divisions_button"):
            self.stop_all_divisions_button.setEnabled(self._all_division_is_active())
```

Add this helper near `_runner_is_active`:

```python
    def _all_division_is_active(self) -> bool:
        return bool(self.all_division_fetch_threads or self.all_division_run_threads)
```

- [ ] **Step 4: Add placeholder command handlers**

Add these methods near `run_selected_jobs`; Task 4 will fill in the orchestration:

```python
    def run_all_divisions(self) -> None:
        jobs = self.build_all_division_jobs()
        self.all_division_jobs = {str(job["division_code"]): job for job in jobs}
        missing = self.missing_sessions_for_all_division_jobs(jobs)
        if missing:
            message = f"Run All Divisions blocked: missing active sessions for {', '.join(missing)}."
            self.append_log(message)
            for code in missing:
                self.all_division_jobs[code]["status"] = "Blocked"
                self.all_division_jobs[code]["message"] = "Missing active session"
            self.render_all_division_jobs()
            self._refresh_session_status()
            self.tabs.setCurrentIndex(1)
            return
        self.append_log(f"Run All Divisions ready for {len(jobs)} divisions.")
        self.render_all_division_jobs()
        self.tabs.setCurrentIndex(1)

    def stop_all_division_runs(self) -> None:
        for worker in self.all_division_run_workers.values():
            worker.stop()
        for bridge in self.all_division_bridges.values():
            bridge.stop()
        self.append_log("Stop requested for all division runs.")
```

- [ ] **Step 5: Run the focused tests**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_process_tab_has_run_all_divisions_button_and_batch_table tests/test_api_models.py::test_all_division_session_preflight_blocks_missing_session -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: add all-division run controls"
```

### Task 4: Make Parallel Artifacts Collision-Safe

**Files:**
- Modify: `Auto Key In Refactor/app/core/run_artifacts.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing artifact uniqueness test**

Add this test near other `RunPayload` tests:

```python
def test_run_artifact_store_creates_unique_directories_for_parallel_divisions(tmp_path):
    from app.core.run_artifacts import RunArtifactStore

    store = RunArtifactStore(tmp_path)
    payload_ab1 = RunPayload(4, 2026, "AB1", None, None, "PREMI", None, "premi", "multi_tab_shared_session", 5, True, True, None, [])
    payload_p1b = RunPayload(4, 2026, "P1B", None, None, "PREMI", None, "premi", "multi_tab_shared_session", 5, True, True, None, [])

    first = store.create(payload_ab1)
    second = store.create(payload_p1b)

    assert first.directory != second.directory
    assert "AB1" in first.run_id
    assert "P1B" in second.run_id
    assert first.payload_path.exists()
    assert second.payload_path.exists()
```

- [ ] **Step 2: Run the test**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_run_artifact_store_creates_unique_directories_for_parallel_divisions -q
```

Expected: FAIL if run ids do not include division or collide.

- [ ] **Step 3: Update artifact id generation**

Modify `RunArtifactStore.create`:

```python
    def create(self, payload: RunPayload) -> RunArtifactPaths:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        division = (payload.division_code or "DIV").strip().upper()
        run_id_base = f"{timestamp}-{division}-{payload.category_key}-{payload.runner_mode}"
        run_id = run_id_base
        directory = self.root / run_id
        suffix = 1
        while directory.exists():
            suffix += 1
            run_id = f"{run_id_base}-{suffix}"
            directory = self.root / run_id
        directory.mkdir(parents=True, exist_ok=False)
        paths = RunArtifactPaths(
            run_id=run_id,
            directory=directory,
            payload_path=directory / "payload.json",
            result_path=directory / "result.json",
            events_path=directory / "events.ndjson",
        )
        self.write_payload(paths, payload)
        return paths
```

- [ ] **Step 4: Run the artifact test**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_run_artifact_store_creates_unique_directories_for_parallel_divisions -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add "Auto Key In Refactor/app/core/run_artifacts.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "fix: make run artifacts division-specific"
```

### Task 5: Implement Full-Parallel Fetch and Runner Orchestration

**Files:**
- Modify: `Auto Key In Refactor/app/ui/main_window.py`
- Test: `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Write failing orchestration tests**

Add these tests near the batch UI tests:

```python
def test_run_all_divisions_starts_fetch_for_each_division_when_preflight_passes(monkeypatch):
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi")])
    window = MainWindow(config, registry, [DivisionOption("AB1", "AB1"), DivisionOption("P1B", "P1B")])
    window.runner_mode.setCurrentText("dry_run")
    started: list[str] = []
    monkeypatch.setattr(window, "_start_all_division_fetch", lambda job: started.append(job["division_code"]), raising=False)

    window.run_all_divisions()

    assert started == ["AB1", "P1B"]
    assert window.all_division_jobs["AB1"]["status"] == "Fetching"
    assert window.all_division_jobs["P1B"]["status"] == "Fetching"
    window.close()


def test_stop_all_division_runs_stops_all_active_workers_and_bridges():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("AB1", "AB1")])
    worker = Mock()
    bridge = Mock()
    window.all_division_run_workers = {"AB1": worker}
    window.all_division_bridges = {"AB1": bridge}

    window.stop_all_division_runs()

    worker.stop.assert_called_once()
    bridge.stop.assert_called_once()
    window.close()
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_run_all_divisions_starts_fetch_for_each_division_when_preflight_passes tests/test_api_models.py::test_stop_all_division_runs_stops_all_active_workers_and_bridges -q
```

Expected: FAIL because `run_all_divisions` does not start per-division fetches yet.

- [ ] **Step 3: Replace the placeholder `run_all_divisions` with active orchestration**

Use this implementation:

```python
    def run_all_divisions(self) -> None:
        if self._all_division_is_active():
            self.append_log("Run All Divisions already running.")
            return
        jobs = self.build_all_division_jobs()
        if not jobs:
            self.append_log("Run All Divisions blocked: no divisions configured.")
            return
        self.all_division_jobs = {str(job["division_code"]): job for job in jobs}
        missing = self.missing_sessions_for_all_division_jobs(jobs)
        if missing:
            message = f"Run All Divisions blocked: missing active sessions for {', '.join(missing)}."
            self.append_log(message)
            for code in missing:
                self.all_division_jobs[code]["status"] = "Blocked"
                self.all_division_jobs[code]["message"] = "Missing active session"
            self.render_all_division_jobs()
            self._refresh_session_status()
            self.tabs.setCurrentIndex(1)
            return
        self._set_all_division_buttons_enabled(True)
        self.append_log(f"Starting Run All Divisions for {len(jobs)} divisions. Each division uses 5 tabs.")
        for job in jobs:
            job["status"] = "Fetching"
            job["message"] = "Fetching records"
            self._start_all_division_fetch(job)
        self.render_all_division_jobs()
        self.tabs.setCurrentIndex(1)
```

- [ ] **Step 4: Add per-division fetch methods**

Add these methods after `run_all_divisions`:

```python
    def _start_all_division_fetch(self, job: dict[str, Any]) -> None:
        division_code = str(job["division_code"])
        client = self._api_client()
        query = self.build_query_from_all_division_job(job)
        thread = QThread(self)
        worker = FetchWorker(client, query)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(lambda records, verification, code=division_code: self._handle_all_division_fetch_completed(code, records, verification))
        worker.failed.connect(lambda message, code=division_code: self._handle_all_division_fetch_failed(code, message))
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda code=division_code: self._cleanup_all_division_fetch(code))
        self.all_division_fetch_threads[division_code] = thread
        self.all_division_fetch_workers[division_code] = worker
        thread.start()

    def _cleanup_all_division_fetch(self, division_code: str) -> None:
        self.all_division_fetch_threads.pop(division_code, None)
        self.all_division_fetch_workers.pop(division_code, None)
        self._finish_all_division_batch_if_idle()

    def _handle_all_division_fetch_failed(self, division_code: str, message: str) -> None:
        job = self.all_division_jobs.get(division_code)
        if job:
            job["status"] = "Failed"
            job["message"] = f"Fetch failed: {message}"
        self.append_log(f"[{division_code}] Fetch failed: {message}")
        self.render_all_division_jobs()

    def _handle_all_division_fetch_completed(
        self,
        division_code: str,
        records: list[ManualAdjustmentRecord],
        verification: FetchVerificationStatus | None = None,
    ) -> None:
        job = self.all_division_jobs.get(division_code)
        if not job:
            return
        prepared = prepare_records_for_run(
            records,
            str(job.get("category_key") or ""),
            division_code,
            job.get("row_limit"),
            self.process_only_miss.isChecked(),
            verification or {},
        )
        job["records_total"] = len(prepared.records)
        if prepared.division_rejected_records:
            examples = ", ".join(record.emp_code for record in prepared.division_rejected_records[:10])
            self.append_log(f"[{division_code}] Division prefix guard skipped {len(prepared.division_rejected_records)} records: {examples}.")
        if not prepared.records:
            job["status"] = "Completed"
            job["message"] = "No records"
            self.append_log(f"[{division_code}] No records found after filters.")
            self.render_all_division_jobs()
            return
        job["status"] = "Running"
        job["message"] = f"Running {len(prepared.records)} records"
        self.render_all_division_jobs()
        payload = self.build_payload_from_all_division_job(job, prepared.records)
        self._start_all_division_runner(division_code, payload)
```

- [ ] **Step 5: Add per-division runner methods**

Add these methods after the fetch methods:

```python
    def _start_all_division_runner(self, division_code: str, payload: RunPayload) -> None:
        artifacts = self.artifact_store.create(payload)
        self.all_division_artifacts[division_code] = artifacts
        self.append_log(f"[{division_code}] Payload saved: {artifacts.payload_path}")
        bridge = RunnerBridge(self.config.runner_command)
        thread = QThread(self)
        worker = RunWorker(bridge, payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(lambda event, code=division_code: self._handle_all_division_runner_event(code, event))
        worker.completed.connect(lambda result, code=division_code: self._handle_all_division_run_completed(code, result))
        worker.failed.connect(lambda message, code=division_code: self._handle_all_division_run_failed(code, message))
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda code=division_code: self._cleanup_all_division_runner(code))
        self.all_division_bridges[division_code] = bridge
        self.all_division_run_threads[division_code] = thread
        self.all_division_run_workers[division_code] = worker
        thread.start()

    def _handle_all_division_runner_event(self, division_code: str, event: RunnerEvent) -> None:
        job = self.all_division_jobs.get(division_code)
        artifacts = self.all_division_artifacts.get(division_code)
        if artifacts:
            self.artifact_store.append_event(artifacts, event.payload)
        message = str(event.payload.get("message") or event.event)
        if job:
            job["message"] = message
            if event.event == "row.success":
                job["success_count"] = int(job.get("success_count") or 0) + 1
            elif event.event == "row.failed":
                job["failed_count"] = int(job.get("failed_count") or 0) + 1
        self.append_log(f"[{division_code}] {message}")
        self.render_all_division_jobs()

    def _handle_all_division_run_completed(self, division_code: str, result: object) -> None:
        job = self.all_division_jobs.get(division_code)
        artifacts = self.all_division_artifacts.get(division_code)
        if artifacts and isinstance(result, dict):
            self.artifact_store.write_result(artifacts, result)
            self.append_log(f"[{division_code}] Result saved: {artifacts.result_path}")
        if job:
            job["status"] = "Completed"
            job["message"] = "Runner completed"
        self.append_log(f"[{division_code}] Runner completed.")
        self.render_all_division_jobs()
        self._refresh_session_status()

    def _handle_all_division_run_failed(self, division_code: str, message: str) -> None:
        job = self.all_division_jobs.get(division_code)
        artifacts = self.all_division_artifacts.get(division_code)
        if artifacts:
            self.artifact_store.write_result(artifacts, {"success": False, "error_summary": message})
            self.append_log(f"[{division_code}] Failure result saved: {artifacts.result_path}")
        if job:
            job["status"] = "Failed"
            job["message"] = message
        self.append_log(f"[{division_code}] Runner failed: {message}")
        self.render_all_division_jobs()
        self._refresh_session_status()

    def _cleanup_all_division_runner(self, division_code: str) -> None:
        self.all_division_run_threads.pop(division_code, None)
        self.all_division_run_workers.pop(division_code, None)
        self.all_division_bridges.pop(division_code, None)
        self._finish_all_division_batch_if_idle()

    def _finish_all_division_batch_if_idle(self) -> None:
        if self._all_division_is_active():
            return
        if not self.all_division_jobs:
            return
        self._set_all_division_buttons_enabled(False)
        completed = sum(1 for job in self.all_division_jobs.values() if str(job.get("status")) == "Completed")
        failed = sum(1 for job in self.all_division_jobs.values() if str(job.get("status")) == "Failed")
        blocked = sum(1 for job in self.all_division_jobs.values() if str(job.get("status")) == "Blocked")
        self.append_log(f"Run All Divisions finished. Completed: {completed}, failed: {failed}, blocked: {blocked}.")
        self.status_bar.showMessage("Ready")
        self.progress_bar.setVisible(False)
```

- [ ] **Step 6: Ensure stop also stops batch runs**

Append this to `stop_run`:

```python
        self.stop_all_division_runs()
```

Update `stop_all_division_runs` to also mark running/fetching jobs:

```python
    def stop_all_division_runs(self) -> None:
        for worker in self.all_division_run_workers.values():
            worker.stop()
        for bridge in self.all_division_bridges.values():
            bridge.stop()
        for job in self.all_division_jobs.values():
            if str(job.get("status")) in {"Fetching", "Running"}:
                job["status"] = "Stopping"
                job["message"] = "Stop requested"
        self.render_all_division_jobs()
        self.append_log("Stop requested for all division runs.")
```

- [ ] **Step 7: Run focused orchestration tests**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py::test_run_all_divisions_starts_fetch_for_each_division_when_preflight_passes tests/test_api_models.py::test_stop_all_division_runs_stops_all_active_workers_and_bridges -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "feat: run all divisions in parallel"
```

### Task 6: Verify the Integrated Behavior

**Files:**
- Modify only if tests expose an issue: `Auto Key In Refactor/app/ui/main_window.py`, `Auto Key In Refactor/app/core/run_artifacts.py`, `Auto Key In Refactor/tests/test_api_models.py`

- [ ] **Step 1: Run the Python test file**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py -q
```

Expected: PASS. If a failure points to an import conflict from the new tests, merge duplicate import lines rather than deleting existing imported names.

- [ ] **Step 2: Build the TypeScript runner**

```powershell
npm --prefix runner run build
```

Expected: PASS because no TypeScript behavior changed.

- [ ] **Step 3: Manual smoke test the UI startup**

```powershell
python -m app
```

Expected:

- App opens.
- Process tab shows `Run All Divisions`, `Stop All Divisions`, and `All Division Run Status`.
- Choosing `Adjustment Name = ALL` and `Runner Mode = dry_run`, then clicking `Run All Divisions`, populates the status table with one row per configured division.

- [ ] **Step 4: Commit any verification fixes**

Only if Step 1 or Step 2 required fixes:

```powershell
git add "Auto Key In Refactor/app/ui/main_window.py" "Auto Key In Refactor/app/core/run_artifacts.py" "Auto Key In Refactor/tests/test_api_models.py"
git commit -m "fix: stabilize all-division run"
```

If there were no fixes, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Full parallel all divisions: Task 5.
- One runner/window per division: Task 5 starts one `RunnerBridge` and `RunWorker` per division.
- Five tabs per division: Task 2 fixes batch payload `max_tabs=5`.
- Specific adjustment name or ALL: Task 2.
- Session isolation and preflight: Task 3.
- Per-division status: Task 3 and Task 5.
- Artifact safety for simultaneous runners: Task 4.
- Tests and verification: Tasks 1 through 6.

Placeholder scan:

- No plan step uses deferred placeholders. Every code-writing step includes concrete code.

Type consistency:

- Batch job fields match the spec and are reused by `build_query_from_all_division_job`, `build_payload_from_all_division_job`, and status rendering.
- The active dictionaries are keyed by uppercase division code.
- `PreparedRunRecords` is returned by `prepare_records_for_run` and consumed by both single-run and batch-run flows.
