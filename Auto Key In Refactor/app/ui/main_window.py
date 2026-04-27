from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.category_registry import CategoryRegistry
from app.core.config import AppConfig, DivisionOption
from app.core.models import ManualAdjustmentRecord, RunPayload
from app.core.run_artifacts import RunArtifactPaths, RunArtifactStore
from app.core.run_service import apply_row_limit, filter_by_category
from app.core.runner_bridge import RunnerBridge, RunnerEvent


class FetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, query: ManualAdjustmentQuery) -> None:
        super().__init__()
        self.client = client
        self.query = query

    def run(self) -> None:
        try:
            self.completed.emit(self.client.get_adjustments(self.query))
        except Exception as exc:
            self.failed.emit(str(exc))


class RunWorker(QObject):
    event_received = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, bridge: RunnerBridge, payload: RunPayload) -> None:
        super().__init__()
        self.bridge = bridge
        self.payload = payload

    def run(self) -> None:
        try:
            result = self.bridge.run(self.payload, self.event_received.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self) -> None:
        self.bridge.stop()


class VerifyWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, period_month: int, period_year: int, emp_codes: list[str], filters: list[str]) -> None:
        super().__init__()
        self.client = client
        self.period_month = period_month
        self.period_year = period_year
        self.emp_codes = emp_codes
        self.filters = filters

    def run(self) -> None:
        try:
            self.completed.emit(self.client.check_adtrans(self.period_month, self.period_year, self.emp_codes, self.filters))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, categories: CategoryRegistry, divisions: list[DivisionOption] | None = None) -> None:
        super().__init__()
        self.config = config
        self.categories = categories
        self.divisions = divisions or []
        self.records: list[ManualAdjustmentRecord] = []
        self.fetch_thread: QThread | None = None
        self.fetch_worker: FetchWorker | None = None
        self.run_thread: QThread | None = None
        self.run_worker: RunWorker | None = None
        self.verify_thread: QThread | None = None
        self.verify_worker: VerifyWorker | None = None
        self.runner_bridge: RunnerBridge | None = None
        self.artifact_store = RunArtifactStore()
        self.current_artifacts: RunArtifactPaths | None = None
        self.tab_progress: dict[int, dict[str, object]] = {}
        self.record_status: dict[str, dict[str, Any]] = {}
        self.last_run_result: dict[str, Any] | None = None
        self.last_successful_records: list[ManualAdjustmentRecord] = []
        self.setWindowTitle("Auto Key In Refactor")
        self.resize(1500, 920)
        self._build_ui()
        self.apply_category_preset()
        self._sync_verify_defaults()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        title = QLabel("PlantwareP3 Auto Key-In Dashboard")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 700; padding: 8px;")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_config_tab(), "Config")
        self.tabs.addTab(self._build_process_tab(), "Process")
        self.tabs.addTab(self._build_summary_tab(), "Summary")
        self.tabs.addTab(self._build_verify_tab(), "Verify db_ptrj")
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)

    def _build_config_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        api_group = QGroupBox("API Settings")
        api_form = QFormLayout(api_group)
        self.api_base_url = QLineEdit(self.config.api_base_url)
        self.api_key = QLineEdit(self.config.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_form.addRow("API Base URL", self.api_base_url)
        api_form.addRow("API Key", self.api_key)

        filter_group = QGroupBox("Data Filter")
        filter_form = QFormLayout(filter_group)
        self.period_month = QSpinBox()
        self.period_month.setRange(1, 12)
        self.period_month.setValue(self.config.default_period_month)
        self.period_year = QSpinBox()
        self.period_year.setRange(2000, 2100)
        self.period_year.setValue(self.config.default_period_year)
        self.division_code = QComboBox()
        self._populate_division_dropdown()
        self.gang_code = QLineEdit()
        self.emp_code = QLineEdit()
        self.adjustment_type = QComboBox()
        self.adjustment_type.addItems(["", "AUTO_BUFFER", "PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "PENDAPATAN_LAINNYA"])
        self.adjustment_name = QLineEdit()
        self.category = QComboBox()
        for item in self.categories.categories:
            self.category.addItem(item.label, item.key)
        self.category.currentIndexChanged.connect(self.apply_category_preset)
        filter_form.addRow("Period Month", self.period_month)
        filter_form.addRow("Period Year", self.period_year)
        filter_form.addRow("Division", self.division_code)
        filter_form.addRow("Gang", self.gang_code)
        filter_form.addRow("Employee", self.emp_code)
        filter_form.addRow("Adjustment Type", self.adjustment_type)
        filter_form.addRow("Adjustment Name", self.adjustment_name)
        filter_form.addRow("Category", self.category)

        runner_group = QGroupBox("Runner Settings")
        runner_form = QFormLayout(runner_group)
        self.runner_mode = QComboBox()
        self.runner_mode.addItems(["multi_tab_shared_session", "dry_run", "session_reuse_single", "fresh_login_single", "get_session", "test_session", "mock"])
        self.max_tabs = QSpinBox()
        self.max_tabs.setRange(1, 10)
        self.max_tabs.setValue(self.config.default_max_tabs)
        self.row_limit = QSpinBox()
        self.row_limit.setRange(0, 10000)
        self.row_limit.setSpecialValueText("No limit")
        self.row_limit.valueChanged.connect(self._update_process_context)
        self.headless = QCheckBox("Headless")
        self.headless.setChecked(self.config.headless)
        self.only_missing = QCheckBox("Only missing rows")
        self.only_missing.setChecked(True)
        runner_form.addRow("Runner Mode", self.runner_mode)
        runner_form.addRow("Max Tabs", self.max_tabs)
        runner_form.addRow("Row Limit", self.row_limit)
        runner_form.addRow(self.headless)
        runner_form.addRow(self.only_missing)

        grid = QGridLayout()
        grid.addWidget(api_group, 0, 0)
        grid.addWidget(filter_group, 1, 0)
        grid.addWidget(runner_group, 0, 1, 2, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        self.apply_preset_button = QPushButton("Apply Category Preset")
        self.get_session_button = QPushButton("Get Session")
        self.test_session_button = QPushButton("Test Session")
        self.apply_preset_button.clicked.connect(self.apply_category_preset)
        self.get_session_button.clicked.connect(self.get_session)
        self.test_session_button.clicked.connect(self.test_session)
        actions.addWidget(self.apply_preset_button)
        actions.addWidget(self.get_session_button)
        actions.addWidget(self.test_session_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return tab

    def _build_process_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.test_get_data_button = QPushButton("Fetch / Refresh Data")
        self.run_button = QPushButton("Run Auto Key-In")
        self.stop_button = QPushButton("Stop")
        self.export_button = QPushButton("Open Artifacts")
        self.stop_button.setEnabled(False)
        self.process_context_label = QLabel("No data loaded.")
        self.test_get_data_button.clicked.connect(self.fetch_records)
        self.run_button.clicked.connect(self.run_auto_key_in)
        self.stop_button.clicked.connect(self.stop_run)
        self.export_button.clicked.connect(self.open_current_artifacts)
        for button in [self.test_get_data_button, self.run_button, self.stop_button, self.export_button]:
            controls.addWidget(button)
        controls.addWidget(self.process_context_label, 1)
        layout.addLayout(controls)

        self.records_table = QTableWidget(0, 12)
        self.records_table.setHorizontalHeaderLabels(["Status", "Sync", "Match", "Emp Code", "Gang", "Division", "Adjustment", "Description", "Adcode", "Remarks Adcode", "Amount", "Remarks"])
        self.records_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.records_table, 3)

        live_group = QGroupBox("Sedang Input")
        live_grid = QGridLayout(live_group)
        self.live_emp_label = QLabel("-")
        self.live_adjustment_label = QLabel("-")
        self.live_description_label = QLabel("-")
        self.live_amount_label = QLabel("-")
        self.live_agent_label = QLabel("-")
        self.live_message_label = QLabel("-")
        live_grid.addWidget(QLabel("Employee"), 0, 0)
        live_grid.addWidget(self.live_emp_label, 0, 1)
        live_grid.addWidget(QLabel("Adjustment"), 0, 2)
        live_grid.addWidget(self.live_adjustment_label, 0, 3)
        live_grid.addWidget(QLabel("Description"), 1, 0)
        live_grid.addWidget(self.live_description_label, 1, 1)
        live_grid.addWidget(QLabel("Amount"), 1, 2)
        live_grid.addWidget(self.live_amount_label, 1, 3)
        live_grid.addWidget(QLabel("Agent/Tab"), 2, 0)
        live_grid.addWidget(self.live_agent_label, 2, 1)
        live_grid.addWidget(QLabel("Message"), 2, 2)
        live_grid.addWidget(self.live_message_label, 2, 3)
        layout.addWidget(live_group)

        self.agent_table = QTableWidget(0, 7)
        self.agent_table.setHorizontalHeaderLabels(["Agent/Tab", "State", "Assigned", "Done", "Skipped", "Failed", "Current Emp"])
        self.agent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.agent_table, 1)

        self.run_table = QTableWidget(0, 7)
        self.run_table.setHorizontalHeaderLabels(["Time", "Status", "Emp Code", "Adjustment", "Amount", "Agent/Tab", "Message"])
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.run_table, 2)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(140)
        layout.addWidget(self.log_output)
        return tab

    def _build_summary_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cards = QGridLayout()
        self.summary_total_fetched = QLabel("0")
        self.summary_attempted = QLabel("0")
        self.summary_success = QLabel("0")
        self.summary_skipped = QLabel("0")
        self.summary_failed = QLabel("0")
        self.summary_success_amount = QLabel("0")
        self.summary_failed_amount = QLabel("0")
        labels = [
            ("Total Fetched", self.summary_total_fetched),
            ("Attempted", self.summary_attempted),
            ("Success", self.summary_success),
            ("Skipped", self.summary_skipped),
            ("Failed", self.summary_failed),
            ("Success Amount", self.summary_success_amount),
            ("Failed Amount", self.summary_failed_amount),
        ]
        for index, (title, value) in enumerate(labels):
            group = QGroupBox(title)
            inner = QVBoxLayout(group)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet("font-size: 22px; font-weight: 700;")
            inner.addWidget(value)
            cards.addWidget(group, index // 4, index % 4)
        layout.addLayout(cards)

        self.summary_table = QTableWidget(0, 10)
        self.summary_table.setHorizontalHeaderLabels(["Status", "Sync", "Match", "Emp Code", "Adjustment", "Description", "Adcode", "Amount", "Message", "Agent/Tab"])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.summary_table, 1)
        return tab

    def _build_verify_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QGroupBox("Check data yang sudah masuk ke db_ptrj")
        form = QFormLayout(controls)
        self.verify_month = QSpinBox()
        self.verify_month.setRange(1, 12)
        self.verify_month.setValue(self.config.default_period_month)
        self.verify_year = QSpinBox()
        self.verify_year.setRange(2000, 2100)
        self.verify_year.setValue(self.config.default_period_year)
        self.verify_emp_codes = QTextEdit()
        self.verify_emp_codes.setPlaceholderText("B0065\nB0070 atau B0065, B0070")
        self.verify_emp_codes.setMaximumHeight(90)
        self.verify_filters = QLineEdit("spsi")
        self.use_last_run_button = QPushButton("Use Last Run Employees")
        self.verify_button = QPushButton("Check db_ptrj")
        self.verify_status_label = QLabel("Belum dicek.")
        self.use_last_run_button.clicked.connect(self.use_last_run_employees)
        self.verify_button.clicked.connect(self.check_db_ptrj)
        action_row = QHBoxLayout()
        action_row.addWidget(self.use_last_run_button)
        action_row.addWidget(self.verify_button)
        action_row.addWidget(self.verify_status_label, 1)
        form.addRow("Period Month", self.verify_month)
        form.addRow("Period Year", self.verify_year)
        form.addRow("Emp Codes", self.verify_emp_codes)
        form.addRow("Filters", self.verify_filters)
        form.addRow(action_row)
        layout.addWidget(controls)

        self.verify_table = QTableWidget(0, 7)
        self.verify_table.setHorizontalHeaderLabels(["Emp Code", "Filter", "Expected", "Actual db_ptrj", "Status", "Adjustment", "Message"])
        self.verify_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.verify_table, 1)
        return tab

    def apply_category_preset(self) -> None:
        category_key = str(self.category.currentData() or "")
        if category_key == "spsi":
            self.adjustment_type.setCurrentText("AUTO_BUFFER")
            self.adjustment_name.setText("AUTO SPSI")
            self.only_missing.setChecked(True)
            self.runner_mode.setCurrentText("multi_tab_shared_session")
        elif category_key == "masa_kerja":
            self.adjustment_type.setCurrentText("AUTO_BUFFER")
            self.adjustment_name.setText("MASA KERJA")
            self.only_missing.setChecked(True)
        elif category_key == "tunjangan_jabatan":
            self.adjustment_type.setCurrentText("AUTO_BUFFER")
            self.adjustment_name.setText("TUNJANGAN JABATAN")
            self.only_missing.setChecked(True)
        self._sync_verify_defaults()
        self._update_process_context()

    def fetch_records(self) -> None:
        self.test_get_data_button.setEnabled(False)
        self.append_log("Fetching manual adjustment data...")
        client = self._api_client()
        query = ManualAdjustmentQuery(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=self._selected_division_code() or None,
            gang_code=self.gang_code.text().strip() or None,
            emp_code=self.emp_code.text().strip() or None,
            adjustment_type=self.adjustment_type.currentText().strip() or None,
            adjustment_name=self.adjustment_name.text().strip() or None,
        )
        self.fetch_thread = QThread(self)
        self.fetch_worker = FetchWorker(client, query)
        self.fetch_worker.moveToThread(self.fetch_thread)
        self.fetch_thread.started.connect(self.fetch_worker.run)
        self.fetch_worker.completed.connect(self._handle_fetch_completed)
        self.fetch_worker.failed.connect(self._handle_fetch_failed)
        self.fetch_worker.completed.connect(self.fetch_thread.quit)
        self.fetch_worker.failed.connect(self.fetch_thread.quit)
        self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
        self.fetch_thread.start()

    def _handle_fetch_completed(self, records: list[ManualAdjustmentRecord]) -> None:
        category_key = self.category.currentData()
        row_limit = self.row_limit.value() or None
        self.records = apply_row_limit(filter_by_category(records, category_key), row_limit)
        self.set_records(self.records)
        self.append_log(f"Fetched {len(records)} records; previewing {len(self.records)} records.")
        self.test_get_data_button.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def _handle_fetch_failed(self, message: str) -> None:
        self.append_log(f"Fetch failed: {message}")
        self.process_context_label.setText("Fetch failed. Check logs.")
        self.test_get_data_button.setEnabled(True)

    def get_session(self) -> None:
        self.run_session_command("get_session")

    def test_session(self) -> None:
        self.run_session_command("test_session")

    def run_session_command(self, mode: str) -> None:
        payload = self.build_payload(mode=mode, records=[])
        self.start_runner(payload, f"Starting {mode.replace('_', ' ')}...")
        self.tabs.setCurrentIndex(1)

    def run_auto_key_in(self) -> None:
        if not self.records:
            self.append_log("Run blocked: no records loaded. Click Fetch / Refresh Data first.")
            self.tabs.setCurrentIndex(1)
            return
        mode = self.runner_mode.currentText()
        if str(self.category.currentData() or "") == "spsi" and mode not in {"dry_run", "mock"}:
            self.adjustment_type.setCurrentText("AUTO_BUFFER")
            self.adjustment_name.setText("AUTO SPSI")
            self.only_missing.setChecked(True)
            self.runner_mode.setCurrentText("multi_tab_shared_session")
            mode = "multi_tab_shared_session"
            self.append_log("SPSI preset enforced: AUTO_BUFFER / AUTO SPSI / only missing rows / multi-tab shared session.")
        self._reset_record_status()
        payload = self.build_payload(mode=mode, records=self.records)
        self.start_runner(payload, f"Starting runner for {len(self.records)} records...")
        self.tabs.setCurrentIndex(1)

    def build_payload(self, mode: str, records: list[ManualAdjustmentRecord]) -> RunPayload:
        category_key = str(self.category.currentData() or "spsi")
        return RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=self._selected_division_code(),
            gang_code=self.gang_code.text().strip().upper() or None,
            emp_code=self.emp_code.text().strip().upper() or None,
            adjustment_type=self.adjustment_type.currentText().strip().upper() or None,
            adjustment_name=self.adjustment_name.text().strip() or None,
            category_key=category_key,
            runner_mode=mode,
            max_tabs=self.max_tabs.value(),
            headless=self.headless.isChecked(),
            only_missing_rows=self.only_missing.isChecked(),
            row_limit=self.row_limit.value() or None,
            records=records,
        )

    def start_runner(self, payload: RunPayload, start_message: str) -> None:
        self.run_button.setEnabled(False)
        self.get_session_button.setEnabled(False)
        self.test_session_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.run_table.setRowCount(0)
        self.agent_table.setRowCount(0)
        self.tab_progress = {}
        self.current_artifacts = self.artifact_store.create(payload)
        self.append_log(f"Payload saved: {self.current_artifacts.payload_path}")
        self.runner_bridge = RunnerBridge(self.config.runner_command)
        self.run_thread = QThread(self)
        self.run_worker = RunWorker(self.runner_bridge, payload)
        self.run_worker.moveToThread(self.run_thread)
        self.run_thread.started.connect(self.run_worker.run)
        self.run_worker.event_received.connect(self._handle_runner_event)
        self.run_worker.completed.connect(self._handle_run_completed)
        self.run_worker.failed.connect(self._handle_run_failed)
        self.run_worker.completed.connect(self.run_thread.quit)
        self.run_worker.failed.connect(self.run_thread.quit)
        self.run_thread.finished.connect(self.run_thread.deleteLater)
        self.append_log(start_message)
        self.run_thread.start()

    def stop_run(self) -> None:
        if self.run_worker:
            self.run_worker.stop()
        self.append_log("Stop requested.")

    def open_current_artifacts(self) -> None:
        if not self.current_artifacts:
            self.append_log("No run artifacts available yet.")
            return
        path = self.current_artifacts.directory
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.append_log(f"Opened run artifacts: {path}" if opened else f"Could not open run artifacts: {path}")

    def _handle_runner_event(self, event: RunnerEvent) -> None:
        payload = event.payload
        if self.current_artifacts:
            self.artifact_store.append_event(self.current_artifacts, payload)
        message = str(payload.get("message") or event.event)
        self.append_log(message)
        if event.event.startswith("tab.") or event.event.startswith("row."):
            self.update_agent_progress(event.event, payload)
        if event.event.startswith("row."):
            self._update_record_from_event(event.event, payload, message)
        if event.event.startswith("row.") or event.event.startswith("session.") or event.event.startswith("tab."):
            self._append_event_row(event.event, payload, message)

    def _append_event_row(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        record = self._find_record(str(payload.get("emp_code", "")), str(payload.get("adjustment_name", "")))
        row = self.run_table.rowCount()
        self.run_table.insertRow(row)
        values = [
            datetime.now().strftime("%H:%M:%S"),
            event_name,
            str(payload.get("emp_code", "")),
            str(payload.get("adjustment_name", record.adjustment_name if record else "")),
            f"{record.amount:g}" if record else "",
            str(payload.get("tab_index", "")),
            message,
        ]
        for column, value in enumerate(values):
            self.run_table.setItem(row, column, QTableWidgetItem(value))

    def update_agent_progress(self, event_name: str, payload: dict) -> None:
        tab_value = payload.get("tab_index")
        if tab_value in (None, ""):
            return
        tab_index = int(tab_value)
        progress = self.tab_progress.setdefault(tab_index, {"state": "Pending", "assigned": 0, "done": 0, "skipped": 0, "failed": 0, "current_emp": ""})
        if event_name == "tab.assigned":
            progress.update({"state": "Assigned", "assigned": int(payload.get("assigned_rows") or 0)})
        elif event_name == "tab.open.started":
            progress["state"] = "Opening"
        elif event_name in {"tab.form.ready", "tab.ready"}:
            progress["state"] = "Ready"
        elif event_name == "row.started":
            progress.update({"state": "Inputting", "current_emp": str(payload.get("emp_code", ""))})
        elif event_name == "tab.progress":
            progress.update({
                "state": "Processing",
                "done": int(payload.get("done") or 0),
                "skipped": int(payload.get("skipped") or 0),
                "failed": int(payload.get("failed") or 0),
                "assigned": int(payload.get("total") or progress.get("assigned") or 0),
                "current_emp": str(payload.get("current_emp_code", progress.get("current_emp", ""))),
            })
        elif event_name == "tab.completed":
            progress.update({"state": "Completed", "done": int(payload.get("done") or 0), "skipped": int(payload.get("skipped") or 0), "failed": int(payload.get("failed") or 0), "assigned": int(payload.get("total") or progress.get("assigned") or 0)})
        elif event_name == "tab.submit.started":
            progress["state"] = "Submitting"
        elif event_name == "tab.submit.completed":
            progress["state"] = "Submitted"
        elif event_name in {"tab.open.failed", "row.failed"}:
            progress["state"] = "Failed"
        self.render_agent_progress()

    def render_agent_progress(self) -> None:
        self.agent_table.setRowCount(len(self.tab_progress))
        for row, tab_index in enumerate(sorted(self.tab_progress)):
            progress = self.tab_progress[tab_index]
            values = [str(tab_index), str(progress.get("state", "")), str(progress.get("assigned", 0)), str(progress.get("done", 0)), str(progress.get("skipped", 0)), str(progress.get("failed", 0)), str(progress.get("current_emp", ""))]
            for column, value in enumerate(values):
                self.agent_table.setItem(row, column, QTableWidgetItem(value))
        totals = {"assigned": 0, "done": 0, "skipped": 0, "failed": 0}
        for progress in self.tab_progress.values():
            for key in totals:
                totals[key] += int(progress.get(key) or 0)
        if totals["assigned"]:
            self.process_context_label.setText(f"Progress: {totals['done']} success/done, {totals['skipped']} skipped, {totals['failed']} failed of {totals['assigned']} records.")

    def _handle_run_completed(self, result: object) -> None:
        if self.current_artifacts and isinstance(result, dict):
            self.artifact_store.write_result(self.current_artifacts, result)
            self.last_run_result = result
            self.append_log(f"Result saved: {self.current_artifacts.result_path}")
        self.append_log("Runner completed.")
        self._set_run_buttons_enabled(True)
        self._refresh_summary()
        self.use_last_run_employees()
        self.tabs.setCurrentIndex(2)

    def _handle_run_failed(self, message: str) -> None:
        if self.current_artifacts:
            self.artifact_store.write_result(self.current_artifacts, {"success": False, "error_summary": message})
            self.append_log(f"Failure result saved: {self.current_artifacts.result_path}")
        self.append_log(f"Runner failed: {message}")
        self._set_run_buttons_enabled(True)
        self._refresh_summary()

    def set_records(self, records: list[ManualAdjustmentRecord]) -> None:
        self.records_table.setRowCount(len(records))
        self.record_status = {}
        for row, record in enumerate(records):
            key = self._record_key(record)
            self.record_status[key] = {"row": row, "status": "Pending", "message": ""}
            values = ["Pending", self._sync_status_from_remarks(record), self._match_status_from_remarks(record), record.emp_code, record.gang_code, record.division_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), self._remarks_adcode(record), f"{record.amount:g}", record.remarks]
            for column, value in enumerate(values):
                self.records_table.setItem(row, column, QTableWidgetItem(value))
        self._update_process_context()
        self._refresh_summary()

    def check_db_ptrj(self) -> None:
        emp_codes = self._parse_list(self.verify_emp_codes.toPlainText())
        filters = self._parse_list(self.verify_filters.text())
        if not emp_codes:
            self.verify_status_label.setText("Emp codes masih kosong.")
            return
        if not filters:
            self.verify_status_label.setText("Filters masih kosong.")
            return
        self.verify_button.setEnabled(False)
        self.verify_status_label.setText("Checking db_ptrj...")
        self.verify_thread = QThread(self)
        self.verify_worker = VerifyWorker(self._api_client(), self.verify_month.value(), self.verify_year.value(), emp_codes, filters)
        self.verify_worker.moveToThread(self.verify_thread)
        self.verify_thread.started.connect(self.verify_worker.run)
        self.verify_worker.completed.connect(self._handle_verify_completed)
        self.verify_worker.failed.connect(self._handle_verify_failed)
        self.verify_worker.completed.connect(self.verify_thread.quit)
        self.verify_worker.failed.connect(self.verify_thread.quit)
        self.verify_thread.finished.connect(self.verify_thread.deleteLater)
        self.verify_thread.start()

    def _handle_verify_completed(self, data: list[dict[str, Any]]) -> None:
        self.verify_button.setEnabled(True)
        self._render_verify_results(data)
        self.verify_status_label.setText(f"Loaded {len(data)} employee rows from db_ptrj.")

    def _handle_verify_failed(self, message: str) -> None:
        self.verify_button.setEnabled(True)
        self.verify_status_label.setText(f"Check failed: {message}")
        self.append_log(f"db_ptrj verification failed: {message}")

    def use_last_run_employees(self) -> None:
        rows = self.last_successful_records or self.records
        emp_codes = sorted({record.emp_code for record in rows if record.emp_code})
        self.verify_emp_codes.setPlainText("\n".join(emp_codes))
        self.verify_month.setValue(self.period_month.value())
        self.verify_year.setValue(self.period_year.value())
        self._sync_verify_defaults()

    def _render_verify_results(self, data: list[dict[str, Any]]) -> None:
        filters = self._parse_list(self.verify_filters.text())
        expected = self._expected_amounts_by_emp_filter()
        rows: list[list[str]] = []
        for item in data:
            emp_code = str(item.get("emp_code") or item.get("EmpCode") or "")
            for filter_name in filters:
                actual = float(item.get(filter_name, 0) or 0)
                expected_amount = expected.get((emp_code, filter_name), 0.0)
                if expected_amount and actual == expected_amount:
                    status = "MATCH"
                elif expected_amount and actual != expected_amount:
                    status = "MISMATCH"
                elif actual:
                    status = "FOUND"
                else:
                    status = "NOT FOUND"
                rows.append([emp_code, filter_name, f"{expected_amount:g}" if expected_amount else "-", f"{actual:g}", status, self._adjustment_for_emp_filter(emp_code, filter_name), ""])
        self.verify_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.verify_table.setItem(row, column, QTableWidgetItem(value))

    def _update_record_from_event(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        record = self._find_record(str(payload.get("emp_code", "")), str(payload.get("adjustment_name", "")))
        if not record:
            return
        key = self._record_key(record)
        row = int(self.record_status.get(key, {}).get("row", -1))
        if row < 0:
            return
        status_map = {"row.started": "Running", "row.success": "Success", "row.skipped": "Skipped", "row.failed": "Failed"}
        status = status_map.get(event_name, event_name)
        self.record_status[key].update({"status": status, "message": message, "tab_index": payload.get("tab_index")})
        self.records_table.setItem(row, 0, QTableWidgetItem(status))
        if event_name == "row.started":
            self.live_emp_label.setText(record.emp_code)
            self.live_adjustment_label.setText(record.adjustment_name)
            self.live_description_label.setText(self._description_for_record(record))
            self.live_amount_label.setText(f"{record.amount:g}")
            self.live_agent_label.setText(str(payload.get("tab_index", "-")))
            self.live_message_label.setText(message)
        elif event_name in {"row.success", "row.skipped", "row.failed"}:
            self.live_message_label.setText(message)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        success_records: list[ManualAdjustmentRecord] = []
        failed_records: list[ManualAdjustmentRecord] = []
        table_rows: list[list[str]] = []
        for record in self.records:
            state = self.record_status.get(self._record_key(record), {})
            status = str(state.get("status", "Pending"))
            if status == "Success":
                success_records.append(record)
            elif status == "Failed":
                failed_records.append(record)
            table_rows.append([status, self._sync_status_from_remarks(record), self._match_status_from_remarks(record), record.emp_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), f"{record.amount:g}", str(state.get("message", "")), str(state.get("tab_index", ""))])
        self.last_successful_records = success_records
        attempted = len([row for row in table_rows if row[0] in {"Success", "Skipped", "Failed"}])
        skipped = len([row for row in table_rows if row[0] == "Skipped"])
        self.summary_total_fetched.setText(str(len(self.records)))
        self.summary_attempted.setText(str(attempted))
        self.summary_success.setText(str(len(success_records)))
        self.summary_skipped.setText(str(skipped))
        self.summary_failed.setText(str(len(failed_records)))
        self.summary_success_amount.setText(f"{sum(record.amount for record in success_records):g}")
        self.summary_failed_amount.setText(f"{sum(record.amount for record in failed_records):g}")
        self.summary_table.setRowCount(len(table_rows))
        for row, values in enumerate(table_rows):
            for column, value in enumerate(values):
                self.summary_table.setItem(row, column, QTableWidgetItem(value))

    def _api_client(self) -> ManualAdjustmentApiClient:
        return ManualAdjustmentApiClient(self.api_base_url.text().strip(), self.api_key.text().strip(), self.categories)

    def _populate_division_dropdown(self) -> None:
        if self.divisions:
            for division in self.divisions:
                self.division_code.addItem(f"{division.code} - {division.label}", division.code)
        else:
            self.division_code.addItem(self.config.default_division_code, self.config.default_division_code)
        default_code = self.config.default_division_code.strip().upper()
        for index in range(self.division_code.count()):
            if str(self.division_code.itemData(index)).upper() == default_code:
                self.division_code.setCurrentIndex(index)
                return

    def _selected_division_code(self) -> str:
        return str(self.division_code.currentData() or self.division_code.currentText()).split("-", 1)[0].strip().upper()

    def _description_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        if category and category.description:
            return category.description
        name = record.adjustment_name.strip()
        return name[5:] if name.upper().startswith("AUTO ") else name

    def _adcode_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        if category and category.adcode:
            return category.adcode
        remarks_adcode = self._remarks_adcode(record)
        if remarks_adcode:
            return remarks_adcode
        return self._description_for_record(record).lower()

    def _remarks_parts(self, record: ManualAdjustmentRecord) -> list[str]:
        return [part.strip() for part in record.remarks.split("|") if part.strip()]

    def _remarks_adcode(self, record: ManualAdjustmentRecord) -> str:
        parts = self._remarks_parts(record)
        return parts[1] if len(parts) >= 2 else ""

    def _remarks_token(self, record: ManualAdjustmentRecord, key: str) -> str:
        prefix = f"{key.lower()}:"
        for part in self._remarks_parts(record):
            if part.lower().startswith(prefix):
                return part.split(":", 1)[1].strip().upper()
        return ""

    def _sync_status_from_remarks(self, record: ManualAdjustmentRecord) -> str:
        explicit_sync = self._remarks_token(record, "sync")
        if explicit_sync:
            return explicit_sync
        parts = self._remarks_parts(record)
        if len(parts) >= 3:
            amount_part = parts[2].replace(",", "")
            try:
                remarks_amount = float(amount_part)
            except ValueError:
                return "UNKNOWN"
            return "MATCH" if remarks_amount == record.amount else "MISMATCH"
        if record.remarks.strip():
            return "MANUAL"
        return "NO REMARKS"

    def _match_status_from_remarks(self, record: ManualAdjustmentRecord) -> str:
        explicit_match = self._remarks_token(record, "match")
        if explicit_match:
            return explicit_match
        return self._sync_status_from_remarks(record)

    def _record_key(self, record: ManualAdjustmentRecord) -> str:
        return f"{record.emp_code}|{record.adjustment_name}|{record.amount:g}"

    def _find_record(self, emp_code: str, adjustment_name: str = "") -> ManualAdjustmentRecord | None:
        emp = emp_code.upper().strip()
        adj = adjustment_name.upper().strip()
        for record in self.records:
            if record.emp_code == emp and (not adj or record.adjustment_name.upper() == adj):
                return record
        return None

    def _reset_record_status(self) -> None:
        for record in self.records:
            key = self._record_key(record)
            row = int(self.record_status.get(key, {}).get("row", -1))
            self.record_status[key] = {"row": row, "status": "Pending", "message": ""}
            if row >= 0:
                self.records_table.setItem(row, 0, QTableWidgetItem("Pending"))
        self.live_emp_label.setText("-")
        self.live_adjustment_label.setText("-")
        self.live_description_label.setText("-")
        self.live_amount_label.setText("-")
        self.live_agent_label.setText("-")
        self.live_message_label.setText("-")
        self._refresh_summary()

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)
        self.get_session_button.setEnabled(enabled)
        self.test_session_button.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)

    def _update_process_context(self) -> None:
        if not hasattr(self, "process_context_label"):
            return
        limit_text = "No limit" if self.row_limit.value() == 0 else str(self.row_limit.value())
        self.process_context_label.setText(f"Fetched: {len(self.records)} | Category: {self.category.currentText()} | Row limit: {limit_text}")

    def _sync_verify_defaults(self) -> None:
        if not hasattr(self, "verify_filters"):
            return
        self.verify_month.setValue(self.period_month.value())
        self.verify_year.setValue(self.period_year.value())
        category_key = str(self.category.currentData() or "")
        defaults = {
            "spsi": "spsi",
            "masa_kerja": "masa kerja",
            "tunjangan_jabatan": "jabatan",
            "premi": "premi",
            "potongan_upah_kotor": "potongan",
            "premi_tunjangan": "premi",
        }
        self.verify_filters.setText(defaults.get(category_key, category_key or "spsi"))

    def _parse_list(self, value: str) -> list[str]:
        return [item.strip() for chunk in value.splitlines() for item in chunk.split(",") if item.strip()]

    def _filter_for_record(self, record: ManualAdjustmentRecord) -> str:
        category_key = record.category_key or ""
        if category_key == "masa_kerja":
            return "masa kerja"
        if category_key == "tunjangan_jabatan":
            return "jabatan"
        if category_key == "potongan_upah_kotor":
            return "potongan"
        if category_key == "premi_tunjangan":
            return "premi"
        return category_key or self._description_for_record(record).lower()

    def _expected_amounts_by_emp_filter(self) -> dict[tuple[str, str], float]:
        expected: dict[tuple[str, str], float] = {}
        for record in self.last_successful_records:
            key = (record.emp_code, self._filter_for_record(record))
            expected[key] = expected.get(key, 0.0) + record.amount
        return expected

    def _adjustment_for_emp_filter(self, emp_code: str, filter_name: str) -> str:
        for record in self.last_successful_records:
            if record.emp_code == emp_code and self._filter_for_record(record) == filter_name:
                return record.adjustment_name
        return ""

    def append_log(self, message: str) -> None:
        self.log_output.append(message)
