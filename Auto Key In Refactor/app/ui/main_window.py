from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.config import AppConfig
from app.core.category_registry import CategoryRegistry
from app.core.models import ManualAdjustmentRecord, RunPayload
from app.core.run_artifacts import RunArtifactPaths, RunArtifactStore
from app.core.runner_bridge import RunnerBridge, RunnerEvent
from app.core.run_service import apply_row_limit, filter_by_category


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


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, categories: CategoryRegistry) -> None:
        super().__init__()
        self.config = config
        self.categories = categories
        self.records: list[ManualAdjustmentRecord] = []
        self.fetch_thread: QThread | None = None
        self.fetch_worker: FetchWorker | None = None
        self.run_thread: QThread | None = None
        self.run_worker: RunWorker | None = None
        self.runner_bridge: RunnerBridge | None = None
        self.artifact_store = RunArtifactStore()
        self.current_artifacts: RunArtifactPaths | None = None
        self.tab_progress: dict[int, dict[str, object]] = {}
        self.setWindowTitle("Auto Key In Refactor")
        self.resize(1280, 820)
        self._build_ui()
        self.apply_category_preset()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        title = QLabel("PlantwareP3 Auto Key-In Controller")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; padding: 8px;")
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        form = QFormLayout()

        self.api_base_url = QLineEdit(self.config.api_base_url)
        self.api_key = QLineEdit(self.config.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.period_month = QSpinBox()
        self.period_month.setRange(1, 12)
        self.period_month.setValue(self.config.default_period_month)
        self.period_year = QSpinBox()
        self.period_year.setRange(2000, 2100)
        self.period_year.setValue(self.config.default_period_year)
        self.division_code = QLineEdit(self.config.default_division_code)
        self.gang_code = QLineEdit()
        self.emp_code = QLineEdit()
        self.adjustment_type = QComboBox()
        self.adjustment_type.addItems(["", "AUTO_BUFFER", "PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "PENDAPATAN_LAINNYA"])
        self.adjustment_name = QLineEdit()
        self.category = QComboBox()
        for item in self.categories.categories:
            self.category.addItem(item.label, item.key)
        self.category.currentIndexChanged.connect(self.apply_category_preset)
        self.runner_mode = QComboBox()
        self.runner_mode.addItems(["multi_tab_shared_session", "dry_run", "session_reuse_single", "fresh_login_single", "get_session", "test_session", "mock"])
        self.max_tabs = QSpinBox()
        self.max_tabs.setRange(1, 10)
        self.max_tabs.setValue(self.config.default_max_tabs)
        self.row_limit = QSpinBox()
        self.row_limit.setRange(0, 10000)
        self.row_limit.setSpecialValueText("No limit")
        self.headless = QCheckBox("Headless")
        self.headless.setChecked(self.config.headless)
        self.only_missing = QCheckBox("Only missing rows")
        self.only_missing.setChecked(True)

        for label, widget in [
            ("API Base URL", self.api_base_url),
            ("API Key", self.api_key),
            ("Period Month", self.period_month),
            ("Period Year", self.period_year),
            ("Division", self.division_code),
            ("Gang", self.gang_code),
            ("Employee", self.emp_code),
            ("Adjustment Type", self.adjustment_type),
            ("Adjustment Name", self.adjustment_name),
            ("Category", self.category),
            ("Runner Mode", self.runner_mode),
            ("Max Tabs", self.max_tabs),
            ("Row Limit", self.row_limit),
        ]:
            form.addRow(label, widget)
        form.addRow(self.headless)
        form.addRow(self.only_missing)
        filter_row.addLayout(form, 2)

        actions = QVBoxLayout()
        self.test_get_data_button = QPushButton("Test Get Data")
        self.get_session_button = QPushButton("Get Session")
        self.test_session_button = QPushButton("Test Session")
        self.preview_button = QPushButton("Preview Records")
        self.run_button = QPushButton("Run Auto Key-In")
        self.stop_button = QPushButton("Stop Run")
        self.export_button = QPushButton("Export Result / Open Logs")
        self.stop_button.setEnabled(False)
        for button in [self.test_get_data_button, self.get_session_button, self.test_session_button, self.preview_button, self.run_button, self.stop_button, self.export_button]:
            actions.addWidget(button)
        actions.addStretch(1)
        filter_row.addLayout(actions, 1)
        layout.addLayout(filter_row)

        self.summary_label = QLabel("No data loaded.")
        layout.addWidget(self.summary_label)

        self.records_table = QTableWidget(0, 7)
        self.records_table.setHorizontalHeaderLabels(["Emp", "Gang", "Division", "Type", "Name", "Amount", "Remarks"])
        self.records_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.records_table, 3)

        self.agent_table = QTableWidget(0, 7)
        self.agent_table.setHorizontalHeaderLabels(["Tab", "State", "Assigned", "Done", "Skipped", "Failed", "Current Emp"])
        self.agent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.agent_table, 1)

        self.run_table = QTableWidget(0, 5)
        self.run_table.setHorizontalHeaderLabels(["Status", "Emp", "Category", "Message", "Tab"])
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.run_table, 2)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output, 2)

        self.test_get_data_button.clicked.connect(self.fetch_records)
        self.get_session_button.clicked.connect(self.get_session)
        self.test_session_button.clicked.connect(self.test_session)
        self.preview_button.clicked.connect(lambda: self.set_records(self.records))
        self.run_button.clicked.connect(self.run_auto_key_in)
        self.stop_button.clicked.connect(self.stop_run)
        self.export_button.clicked.connect(self.open_current_artifacts)
        self.setCentralWidget(root)

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

    def fetch_records(self) -> None:
        self.test_get_data_button.setEnabled(False)
        self.append_log("Fetching manual adjustment data...")
        client = ManualAdjustmentApiClient(
            self.api_base_url.text().strip(),
            self.api_key.text().strip(),
            self.categories,
        )
        query = ManualAdjustmentQuery(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=self.division_code.text().strip() or None,
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

    def _handle_fetch_failed(self, message: str) -> None:
        self.append_log(f"Fetch failed: {message}")
        self.summary_label.setText("Fetch failed. Check logs.")
        self.test_get_data_button.setEnabled(True)

    def get_session(self) -> None:
        self.run_session_command("get_session")

    def test_session(self) -> None:
        self.run_session_command("test_session")

    def run_session_command(self, mode: str) -> None:
        payload = self.build_payload(mode=mode, records=[])
        self.start_runner(payload, f"Starting {mode.replace('_', ' ')}...")

    def run_auto_key_in(self) -> None:
        if not self.records:
            self.append_log("Run blocked: no records loaded. Click Test Get Data first.")
            return
        mode = self.runner_mode.currentText()
        if str(self.category.currentData() or "") == "spsi" and mode not in {"dry_run", "mock"}:
            self.adjustment_type.setCurrentText("AUTO_BUFFER")
            self.adjustment_name.setText("AUTO SPSI")
            self.only_missing.setChecked(True)
            self.runner_mode.setCurrentText("multi_tab_shared_session")
            mode = "multi_tab_shared_session"
            self.append_log("SPSI preset enforced: AUTO_BUFFER / AUTO SPSI / only missing rows / multi-tab shared session.")
        payload = self.build_payload(mode=mode, records=self.records)
        self.start_runner(payload, f"Starting runner for {len(self.records)} records...")

    def build_payload(self, mode: str, records: list[ManualAdjustmentRecord]) -> RunPayload:
        category_key = str(self.category.currentData() or "spsi")
        return RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=self.division_code.text().strip().upper(),
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
        if opened:
            self.append_log(f"Opened run artifacts: {path}")
        else:
            self.append_log(f"Could not open run artifacts: {path}")

    def _handle_runner_event(self, event: RunnerEvent) -> None:
        payload = event.payload
        if self.current_artifacts:
            self.artifact_store.append_event(self.current_artifacts, payload)
        message = str(payload.get("message") or event.event)
        self.append_log(message)
        if event.event.startswith("tab.") or event.event.startswith("row."):
            self.update_agent_progress(event.event, payload)
        if event.event.startswith("row.") or event.event.startswith("session.") or event.event.startswith("tab."):
            row = self.run_table.rowCount()
            self.run_table.insertRow(row)
            values = [
                event.event,
                str(payload.get("emp_code", "")),
                str(payload.get("category_key", payload.get("runner_mode", ""))),
                message,
                str(payload.get("tab_index", "")),
            ]
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(value))

    def update_agent_progress(self, event_name: str, payload: dict) -> None:
        tab_value = payload.get("tab_index")
        if tab_value in (None, ""):
            return
        tab_index = int(tab_value)
        progress = self.tab_progress.setdefault(tab_index, {
            "state": "Pending",
            "assigned": 0,
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "current_emp": "",
        })
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
            progress.update({
                "state": "Completed",
                "done": int(payload.get("done") or 0),
                "skipped": int(payload.get("skipped") or 0),
                "failed": int(payload.get("failed") or 0),
                "assigned": int(payload.get("total") or progress.get("assigned") or 0),
            })
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
            values = [
                str(tab_index),
                str(progress.get("state", "")),
                str(progress.get("assigned", 0)),
                str(progress.get("done", 0)),
                str(progress.get("skipped", 0)),
                str(progress.get("failed", 0)),
                str(progress.get("current_emp", "")),
            ]
            for column, value in enumerate(values):
                self.agent_table.setItem(row, column, QTableWidgetItem(value))
        totals = {"assigned": 0, "done": 0, "skipped": 0, "failed": 0}
        for progress in self.tab_progress.values():
            for key in totals:
                totals[key] += int(progress.get(key) or 0)
        if totals["assigned"]:
            self.summary_label.setText(
                f"Run progress: {totals['done']} done, {totals['skipped']} skipped, {totals['failed']} failed of {totals['assigned']} records across {len(self.tab_progress)} tabs."
            )

    def _handle_run_completed(self, result: object) -> None:
        if self.current_artifacts and isinstance(result, dict):
            self.artifact_store.write_result(self.current_artifacts, result)
            self.append_log(f"Result saved: {self.current_artifacts.result_path}")
        self.append_log("Runner completed.")
        self.run_button.setEnabled(True)
        self.get_session_button.setEnabled(True)
        self.test_session_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _handle_run_failed(self, message: str) -> None:
        if self.current_artifacts:
            self.artifact_store.write_result(self.current_artifacts, {"success": False, "error_summary": message})
            self.append_log(f"Failure result saved: {self.current_artifacts.result_path}")
        self.append_log(f"Runner failed: {message}")
        self.run_button.setEnabled(True)
        self.get_session_button.setEnabled(True)
        self.test_session_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def set_records(self, records: list[ManualAdjustmentRecord]) -> None:
        self.records_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                record.emp_code,
                record.gang_code,
                record.division_code,
                record.adjustment_type,
                record.adjustment_name,
                f"{record.amount:g}",
                record.remarks,
            ]
            for column, value in enumerate(values):
                self.records_table.setItem(row, column, QTableWidgetItem(value))
        self.summary_label.setText(f"Loaded {len(records)} records.")

    def append_log(self, message: str) -> None:
        self.log_output.append(message)
