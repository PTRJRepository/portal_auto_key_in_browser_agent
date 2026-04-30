from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
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
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.ui.division_monitor import DivisionMonitorWidget
from app.ui.themes import AppTheme
from app.core.category_registry import CategoryRegistry
from app.core.config import AppConfig, DivisionOption
from app.core.models import DuplicateDocIdTarget, ManualAdjustmentRecord, RunPayload, enrich_records_with_automation_options, extract_ad_code_from_remarks
from app.core.run_artifacts import RunArtifactPaths, RunArtifactStore
from app.core.run_service import apply_row_limit, filter_by_category
from app.core.runner_bridge import RunnerBridge, RunnerEvent

FetchVerificationStatus = dict[tuple[str, str], dict[str, Any]]
AUTOMATION_OPTION_CATEGORIES = ["premi", "koreksi", "potongan_upah_bersih"]
AUTOMATION_OPTION_TYPES = {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH"}
MANUAL_PREVIEW_CATEGORY_KEYS = {"premi", "premi_tunjangan", "potongan_upah_kotor", "potongan_upah_bersih", "koreksi"}


def remarks_parts(record: ManualAdjustmentRecord) -> list[str]:
    return [part.strip() for part in record.remarks.split("|") if part.strip()]


def remarks_token(record: ManualAdjustmentRecord, key: str) -> str:
    prefix = f"{key.lower()}:"
    for part in remarks_parts(record):
        if part.lower().startswith(prefix):
            return part.split(":", 1)[1].strip().upper()
    return ""


def sync_status_from_remarks(record: ManualAdjustmentRecord) -> str:
    explicit_sync = remarks_token(record, "sync")
    if explicit_sync:
        return explicit_sync
    parts = remarks_parts(record)
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


def match_status_from_remarks(record: ManualAdjustmentRecord) -> str:
    explicit_match = remarks_token(record, "match")
    if explicit_match:
        return explicit_match
    return sync_status_from_remarks(record)


def record_is_stale_miss(record: ManualAdjustmentRecord) -> bool:
    sync_status = sync_status_from_remarks(record).upper()
    match_status = match_status_from_remarks(record).upper()
    return sync_status in {"MISS", "MISSING"} or match_status in {"MISMATCH", "MISS", "MISSING"}


def filter_for_record(record: ManualAdjustmentRecord) -> str:
    category_key = record.category_key or ""
    if category_key == "masa_kerja":
        return "masa kerja"
    if category_key == "tunjangan_jabatan":
        return "jabatan"
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


def build_fetch_verification_status(records: list[ManualAdjustmentRecord], data: list[dict[str, Any]]) -> FetchVerificationStatus:
    expected: dict[tuple[str, str], float] = {}
    for record in records:
        if record_is_stale_miss(record):
            key = (record.emp_code, filter_for_record(record))
            expected[key] = expected.get(key, 0.0) + record.amount
    actual_by_key: dict[tuple[str, str], float] = {}
    for item in data:
        emp_code = str(item.get("emp_code") or item.get("EmpCode") or "").upper().strip()
        for _, filter_name in expected:
            if (emp_code, filter_name) in expected:
                actual_by_key[(emp_code, filter_name)] = float(item.get(filter_name, 0) or 0)
    statuses: FetchVerificationStatus = {}
    for key, expected_amount in expected.items():
        actual = actual_by_key.get(key, 0.0)
        if actual == expected_amount:
            status = "VERIFIED_MATCH"
        elif actual:
            status = "VERIFIED_MISMATCH"
        else:
            status = "VERIFIED_NOT_FOUND"
        statuses[key] = {"status": status, "expected": expected_amount, "actual": actual}
    return statuses


class FetchWorker(QObject):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, query: ManualAdjustmentQuery) -> None:
        super().__init__()
        self.client = client
        self.query = query

    def run(self) -> None:
        try:
            records = self.client.get_adjustments(self.query)
            records = self._enrich_manual_automation_details(records)
            suspect_records = [record for record in records if record_is_stale_miss(record)]
            verification: FetchVerificationStatus = {}
            if suspect_records:
                emp_codes = sorted({record.emp_code for record in suspect_records if record.emp_code})
                filters = sorted({filter_name for record in suspect_records if (filter_name := filter_for_record(record))})
                try:
                    data = self.client.check_adtrans(self.query.period_month, self.query.period_year, emp_codes, filters)
                    verification = build_fetch_verification_status(suspect_records, data)
                except Exception as exc:
                    verification = {
                        (record.emp_code, filter_for_record(record)): {"status": "VERIFY_ERROR", "expected": record.amount, "actual": 0.0, "message": str(exc)}
                        for record in suspect_records
                    }
            self.completed.emit(records, verification)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _enrich_manual_automation_details(self, records: list[ManualAdjustmentRecord]) -> list[ManualAdjustmentRecord]:
        if not self.query.division_code:
            return records
        needs_detail = [
            record for record in records
            if record.adjustment_type in AUTOMATION_OPTION_TYPES and not (record.ad_code and record.task_code and record.task_desc)
        ]
        if not needs_detail:
            return records
        try:
            options = self.client.get_automation_options(
                division_code=self.query.division_code,
                categories=AUTOMATION_OPTION_CATEGORIES,
                limit=200,
            )
        except Exception:
            return records
        return enrich_records_with_automation_options(records, options)


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


class DuplicateFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, period_month: int, period_year: int, division_code: str, filters: list[str]) -> None:
        super().__init__()
        self.client = client
        self.period_month = period_month
        self.period_year = period_year
        self.division_code = division_code
        self.filters = filters

    def run(self) -> None:
        try:
            self.completed.emit(self.client.get_duplicate_delete_targets(self.period_month, self.period_year, self.division_code, self.filters))
        except Exception as exc:
            self.failed.emit(str(exc))


class SessionRefreshWorker(QObject):
    event_received = Signal(str, object)
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, division_code: str, bridge: RunnerBridge, payload: RunPayload) -> None:
        super().__init__()
        self.division_code = division_code
        self.bridge = bridge
        self.payload = payload

    def run(self) -> None:
        try:
            result = self.bridge.run(self.payload, lambda event: self.event_received.emit(self.division_code, event))
            self.completed.emit(self.division_code, result)
        except Exception as exc:
            self.failed.emit(self.division_code, str(exc))

    def stop(self) -> None:
        self.bridge.stop()


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, categories: CategoryRegistry, divisions: list[DivisionOption] | None = None) -> None:
        super().__init__()
        self.config = config
        self.categories = categories
        self.divisions = divisions or []
        self.records: list[ManualAdjustmentRecord] = []
        self.jobs: list[dict[str, Any]] = []
        self.fetch_thread: QThread | None = None
        self.fetch_worker: FetchWorker | None = None
        self.run_thread: QThread | None = None
        self.run_worker: RunWorker | None = None
        self.verify_thread: QThread | None = None
        self.verify_worker: VerifyWorker | None = None
        self.duplicate_fetch_thread: QThread | None = None
        self.duplicate_fetch_worker: DuplicateFetchWorker | None = None
        self.duplicate_targets: list[DuplicateDocIdTarget] = []
        self.duplicate_target_rows: dict[str, int] = {}
        self.runner_bridge: RunnerBridge | None = None
        self.session_refresh_threads: dict[str, QThread] = {}
        self.session_refresh_workers: dict[str, SessionRefreshWorker] = {}
        self.session_refresh_bridges: dict[str, RunnerBridge] = {}
        self.session_refresh_results: dict[str, str] = {}
        self.session_dir_override: Path | None = None
        self.artifact_store = RunArtifactStore()
        self.current_artifacts: RunArtifactPaths | None = None
        self.tab_progress: dict[int, dict[str, object]] = {}
        self.record_status: dict[str, dict[str, Any]] = {}
        self.fetch_verification_status: FetchVerificationStatus = {}
        self.last_run_result: dict[str, Any] | None = None
        self.last_successful_records: list[ManualAdjustmentRecord] = []
        self.division_run_dialogs: list[QDialog] = []
        self.setWindowTitle("Auto Key In Refactor")
        self.resize(1500, 920)
        self._build_ui()
        self._apply_theme()
        self._setup_shortcuts()
        self.apply_category_preset()
        self._sync_verify_defaults()
        self._refresh_session_status()

    def _apply_theme(self) -> None:
        self.setStyleSheet(AppTheme.get_stylesheet())

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.run_auto_key_in)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.fetch_records)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.stop_run)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.tabs.setCurrentIndex(1))
        QShortcut(QKeySequence("Ctrl+3"), self, activated=lambda: self.tabs.setCurrentIndex(2))

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("PlantwareP3 Auto Key-In Dashboard")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_config_tab(), "Config")
        self.tabs.addTab(self._build_process_tab(), "Process")
        self.tabs.addTab(self._build_summary_tab(), "Summary")
        self.tabs.addTab(self._build_verify_tab(), "Verify db_ptrj")
        self.tabs.addTab(self._build_duplicate_cleanup_tab(), "Duplicate Cleanup")
        self.division_monitor = DivisionMonitorWidget(self._api_client, self.categories, self.divisions)
        self.division_monitor.run_division_category.connect(self._on_division_monitor_run)
        self.tabs.addTab(self.division_monitor, "Division Monitor")
        layout.addWidget(self.tabs)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
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
        self.adjustment_type.addItems(["", "AUTO_BUFFER", "MANUAL", "PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "PENDAPATAN_LAINNYA"])
        self.adjustment_type.setToolTip("MANUAL = PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH,PENDAPATAN_LAINNYA; comma-separated values are supported by the API.")
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
        self.session_status_label = QLabel("")
        filter_form.addRow("Selected Session", self.session_status_label)
        self.division_code.currentIndexChanged.connect(self._refresh_session_status)

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

        session_group = QGroupBox("Session Status")
        session_layout = QVBoxLayout(session_group)
        session_actions = QHBoxLayout()
        self.refresh_sessions_button = QPushButton("Refresh Status")
        self.refresh_all_sessions_button = QPushButton("Get All Sessions")
        self.refresh_sessions_button.clicked.connect(self._refresh_session_status)
        self.refresh_all_sessions_button.clicked.connect(self.get_all_sessions)
        session_actions.addWidget(self.refresh_sessions_button)
        session_actions.addWidget(self.refresh_all_sessions_button)
        session_actions.addStretch(1)
        self.session_table = QTableWidget(0, 6)
        self.session_table.setHorizontalHeaderLabels(["Division", "Location", "Status", "Age", "Last Saved", "Action"])
        self.session_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.session_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.session_table.setMaximumHeight(320)
        session_layout.addLayout(session_actions)
        session_layout.addWidget(self.session_table)

        grid = QGridLayout()
        grid.addWidget(api_group, 0, 0)
        grid.addWidget(filter_group, 1, 0)
        grid.addWidget(runner_group, 0, 1)
        grid.addWidget(session_group, 1, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.apply_preset_button = QPushButton("Apply Category Preset")
        self.apply_preset_button.setObjectName("primary")
        self.get_session_button = QPushButton("Get Session")
        self.get_session_button.setObjectName("success")
        self.test_session_button = QPushButton("Test Session")
        self.test_session_button.setObjectName("primary")
        self.add_job_button = QPushButton("Tambahkan Job")
        self.add_job_button.setObjectName("success")
        self.apply_preset_button.clicked.connect(self.apply_category_preset)
        self.get_session_button.clicked.connect(self.get_session)
        self.test_session_button.clicked.connect(self.test_session)
        self.add_job_button.clicked.connect(self.add_job_from_current_config)
        actions.addWidget(self.apply_preset_button)
        actions.addWidget(self.get_session_button)
        actions.addWidget(self.test_session_button)
        actions.addWidget(self.add_job_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return tab

    def _build_process_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.test_get_data_button = QPushButton("Fetch / Refresh Data")
        self.test_get_data_button.setObjectName("primary")
        self.run_button = QPushButton("Run Auto Key-In")
        self.run_button.setObjectName("success")
        self.run_selected_jobs_button = QPushButton("Run Selected Jobs")
        self.run_selected_jobs_button.setObjectName("primary")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.export_button = QPushButton("Open Artifacts")
        self.process_context_label = QLabel("No data loaded.")
        self.process_context_label.setStyleSheet("font-weight: 500; color: #94a3b8;")
        self.process_only_miss = QCheckBox("Input MISS/MISMATCH only")
        self.process_only_miss.setChecked(True)
        self.process_only_miss.setToolTip("Jika aktif, fetch/run hanya memakai row dengan remarks sync:MISS atau match:MISMATCH.")
        self.process_only_miss.stateChanged.connect(self._update_process_context)
        self.test_get_data_button.clicked.connect(self.fetch_records)
        self.run_button.clicked.connect(self.run_auto_key_in)
        self.run_selected_jobs_button.clicked.connect(self.run_selected_jobs)
        self.stop_button.clicked.connect(self.stop_run)
        self.export_button.clicked.connect(self.open_current_artifacts)
        for button in [self.test_get_data_button, self.run_button, self.run_selected_jobs_button, self.stop_button, self.export_button]:
            controls.addWidget(button)
        controls.addWidget(self.process_only_miss)
        controls.addWidget(self.process_context_label, 1)
        layout.addLayout(controls)

        job_group = QGroupBox("Daftar Job")
        job_layout = QVBoxLayout(job_group)
        self.job_table = QTableWidget(0, 10)
        self.job_table.setHorizontalHeaderLabels(["Run", "Division", "Gang", "Category", "Adjustment Type", "Adjustment Name", "Mode", "Max Tabs", "Row Limit", "Status"])
        self.job_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.job_table.setMaximumHeight(180)
        job_layout.addWidget(self.job_table)
        layout.addWidget(job_group)

        self.records_table = QTableWidget(0, 13)
        self.records_table.setHorizontalHeaderLabels(["Input Status", "DB Status", "API Sync", "API Match", "Emp Code", "Gang", "Division", "Adjustment", "Description", "ADCode", "Remarks ADCode", "Amount", "Remarks"])
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

        self.summary_table = QTableWidget(0, 11)
        self.summary_table.setHorizontalHeaderLabels(["Input Status", "DB Status", "API Sync", "API Match", "Emp Code", "Adjustment", "Description", "Adcode", "Amount", "Message", "Agent/Tab"])
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

    def _build_duplicate_cleanup_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QGroupBox("Hapus duplicate DocID Plantware")
        form = QFormLayout(controls)
        self.duplicate_month = QSpinBox()
        self.duplicate_month.setRange(1, 12)
        self.duplicate_month.setValue(self.config.default_period_month)
        self.duplicate_year = QSpinBox()
        self.duplicate_year.setRange(2000, 2100)
        self.duplicate_year.setValue(self.config.default_period_year)
        self.duplicate_filters = QLineEdit("spsi")
        self.duplicate_dry_run = QCheckBox("Dry run: search Plantware, do not delete")
        self.duplicate_dry_run.setChecked(True)
        self.duplicate_dry_run.setToolTip("Browser akan membuka Plantware untuk mencari DocID, tetapi tombol Delete tidak akan diklik.")
        self.fetch_duplicates_button = QPushButton("Fetch Duplicate Targets")
        self.delete_duplicates_button = QPushButton("Delete Selected Duplicates")
        self.delete_duplicates_button.setEnabled(False)
        self.duplicate_status_label = QLabel("Belum dicek.")
        self.fetch_duplicates_button.clicked.connect(self.fetch_duplicate_targets)
        self.delete_duplicates_button.clicked.connect(self.run_duplicate_cleanup)
        action_row = QHBoxLayout()
        action_row.addWidget(self.fetch_duplicates_button)
        action_row.addWidget(self.delete_duplicates_button)
        action_row.addWidget(self.duplicate_dry_run)
        action_row.addWidget(self.duplicate_status_label, 1)
        form.addRow("Period Month", self.duplicate_month)
        form.addRow("Period Year", self.duplicate_year)
        form.addRow("Division", QLabel("Mengikuti division di tab Config"))
        form.addRow("Category", QLabel("Auto Buffer only: SPSI / Masa Kerja / Tunjangan Jabatan"))
        form.addRow("Filters", self.duplicate_filters)
        form.addRow(action_row)
        layout.addWidget(controls)

        self.duplicate_table = QTableWidget(0, 9)
        self.duplicate_table.setHorizontalHeaderLabels(["Select", "Action", "DocID", "Emp Code", "Emp Name", "DocDesc", "Keep DocID", "Status", "Message"])
        self.duplicate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.duplicate_table, 1)
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
        elif category_key == "premi_tunjangan":
            self.adjustment_type.setCurrentText("PREMI")
            self.adjustment_name.setText("TUNJANGAN PREMI")
            self.only_missing.setChecked(False)
            self.process_only_miss.setChecked(False)
        elif category_key == "premi":
            self.adjustment_type.setCurrentText("PREMI")
            self.adjustment_name.clear()
            self.only_missing.setChecked(False)
            self.process_only_miss.setChecked(False)
        elif category_key == "potongan_upah_kotor":
            self.adjustment_type.setCurrentText("POTONGAN_KOTOR")
            self.adjustment_name.clear()
            self.only_missing.setChecked(False)
            self.process_only_miss.setChecked(False)
        elif category_key == "potongan_upah_bersih":
            self.adjustment_type.setCurrentText("POTONGAN_BERSIH")
            self.adjustment_name.clear()
            self.only_missing.setChecked(False)
            self.process_only_miss.setChecked(False)
        self._sync_verify_defaults()
        self._update_process_context()

    def add_job_from_current_config(self) -> None:
        job = {
            "period_month": self.period_month.value(),
            "period_year": self.period_year.value(),
            "division_code": self._selected_division_code(),
            "gang_code": self.gang_code.text().strip().upper(),
            "emp_code": self.emp_code.text().strip().upper(),
            "adjustment_type": self.adjustment_type.currentText().strip().upper(),
            "adjustment_name": self.adjustment_name.text().strip(),
            "category_key": str(self.category.currentData() or ""),
            "runner_mode": self.runner_mode.currentText(),
            "max_tabs": self.max_tabs.value(),
            "headless": self.headless.isChecked(),
            "only_missing_rows": self.only_missing.isChecked(),
            "row_limit": self.row_limit.value() or None,
            "status": "Pending",
            "selected": True,
        }
        self.jobs.append(job)
        self._render_jobs()
        self.append_log(f"Job ditambahkan: {job['division_code']} / {job['category_key']} / {job['adjustment_name']}")
        self.tabs.setCurrentIndex(1)

    def _render_jobs(self) -> None:
        self.job_table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Checked if job.get("selected", True) else Qt.CheckState.Unchecked)
            self.job_table.setItem(row, 0, select_item)
            values = [
                str(job.get("division_code", "")),
                str(job.get("gang_code", "")),
                str(job.get("category_key", "")),
                str(job.get("adjustment_type", "")),
                str(job.get("adjustment_name", "")),
                str(job.get("runner_mode", "")),
                str(job.get("max_tabs", "")),
                str(job.get("row_limit") or "No limit"),
                str(job.get("status", "Pending")),
            ]
            for column, value in enumerate(values, start=1):
                self.job_table.setItem(row, column, QTableWidgetItem(value))

    def selected_jobs(self) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for row, job in enumerate(self.jobs):
            item = self.job_table.item(row, 0)
            job["selected"] = item is None or item.checkState() == Qt.CheckState.Checked
            if job["selected"]:
                selected.append(job)
        return selected

    def build_payload_from_job(self, job: dict[str, Any], records: list[ManualAdjustmentRecord]) -> RunPayload:
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
            max_tabs=int(job.get("max_tabs") or 1),
            headless=bool(job.get("headless")),
            only_missing_rows=bool(job.get("only_missing_rows")),
            row_limit=job.get("row_limit"),
            records=records,
        )

    def run_selected_jobs(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            self.append_log("Tidak ada job yang dipilih.")
            return
        self.append_log(f"Selected jobs ready: {len(jobs)}. Eksekusi queue akan ditambahkan setelah fetch per job.")

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

    def _handle_fetch_completed(self, records: list[ManualAdjustmentRecord], verification: FetchVerificationStatus | None = None) -> None:
        self.fetch_verification_status = verification or {}
        if self.fetch_verification_status:
            counts: dict[str, int] = {}
            for item in self.fetch_verification_status.values():
                status = str(item.get("status") or "")
                counts[status] = counts.get(status, 0) + 1
            self.append_log(f"db_ptrj fetch verification: {len(self.fetch_verification_status)} checked, {counts.get('VERIFIED_MATCH', 0)} match, {counts.get('VERIFIED_MISMATCH', 0)} mismatch, {counts.get('VERIFIED_NOT_FOUND', 0)} not found, {counts.get('VERIFY_ERROR', 0)} error.")
        category_key = str(self.category.currentData() or "")
        row_limit = self.row_limit.value() or None
        filtered_records = filter_by_category(records, category_key)
        manual_preview = category_key in MANUAL_PREVIEW_CATEGORY_KEYS
        if self.process_only_miss.isChecked() and not manual_preview:
            before_miss_filter = len(filtered_records)
            filtered_records = [record for record in filtered_records if self._record_is_miss(record)]
            self.append_log(f"MISS-only filter active: {len(filtered_records)} of {before_miss_filter} category records will be previewed/run.")
        elif self.process_only_miss.isChecked() and manual_preview:
            self.append_log(f"Manual category preview: showing all {len(filtered_records)} category records; MISS-only filter is ignored for {category_key}.")
        self.records = apply_row_limit(filtered_records, row_limit)
        self.set_records(self.records)
        self.append_log(f"Fetched {len(records)} raw records; category {category_key or '-'} has {len(filtered_records)} records; previewing {len(self.records)} records.")
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

    def get_session_for_division(self, division_code: str) -> None:
        self.run_session_command("get_session", division_code=division_code)

    def get_all_sessions(self) -> None:
        if self.session_refresh_threads:
            self.append_log("Get All Sessions already running.")
            return
        division_options = self.divisions or [DivisionOption(self.config.default_division_code, self.config.default_division_code)]
        division_codes = [division.code.strip().upper() for division in division_options if division.code.strip()]
        self.session_refresh_results = {code: "Running" for code in division_codes}
        self._set_run_buttons_enabled(False)
        self.stop_button.setEnabled(True)
        self.append_log(f"Starting {len(division_codes)} browser session logins in parallel...")
        for division_code in division_codes:
            payload = self.build_payload(mode="get_session", records=[], division_code=division_code)
            bridge = RunnerBridge(self.config.runner_command)
            thread = QThread(self)
            worker = SessionRefreshWorker(division_code, bridge, payload)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.event_received.connect(self._handle_session_refresh_event)
            worker.completed.connect(self._handle_session_refresh_completed)
            worker.failed.connect(self._handle_session_refresh_failed)
            worker.completed.connect(thread.quit)
            worker.failed.connect(thread.quit)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda code=division_code: self._cleanup_session_refresh_worker(code))
            self.session_refresh_threads[division_code] = thread
            self.session_refresh_workers[division_code] = worker
            self.session_refresh_bridges[division_code] = bridge
            thread.start()
        self.tabs.setCurrentIndex(1)

    def run_session_command(self, mode: str, division_code: str | None = None) -> None:
        target_division = (division_code or self._selected_division_code()).strip().upper()
        payload = self.build_payload(mode=mode, records=[], division_code=target_division)
        self.start_runner(payload, f"Starting {mode.replace('_', ' ')} for {target_division}...")
        self.tabs.setCurrentIndex(1)

    def run_auto_key_in(self) -> None:
        if not self.records:
            self.append_log("Run blocked: no records loaded. Click Fetch / Refresh Data first.")
            self.tabs.setCurrentIndex(1)
            return
        mode = self.runner_mode.currentText()
        if mode not in {"dry_run", "mock", "fresh_login_single"} and not self._selected_session_active():
            division_code = self._selected_division_code()
            self.append_log(f"Run blocked: no active verified session for {division_code}. Click Get Session for this division first.")
            self._refresh_session_status()
            self.tabs.setCurrentIndex(0)
            return
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

    def build_payload(self, mode: str, records: list[ManualAdjustmentRecord], division_code: str | None = None) -> RunPayload:
        category_key = str(self.category.currentData() or "spsi")
        return RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=(division_code or self._selected_division_code()).strip().upper(),
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
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.status_bar.showMessage("Running...")
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
        self.run_thread.finished.connect(self._clear_run_thread)
        self.append_log(start_message)
        self.run_thread.start()

    def _clear_run_thread(self) -> None:
        self.run_thread = None
        self.run_worker = None
        self.runner_bridge = None

    def stop_run(self) -> None:
        if self.run_worker:
            self.run_worker.stop()
        for worker in self.session_refresh_workers.values():
            worker.stop()
        self.append_log("Stop requested.")

    def _handle_session_refresh_event(self, division_code: str, event: RunnerEvent) -> None:
        message = str(event.payload.get("message") or event.event)
        session_path = event.payload.get("session_path")
        if session_path:
            self.session_dir_override = Path(str(session_path)).parent
            message = f"{message} ({session_path})"
            self._refresh_session_status()
        self.append_log(f"[{division_code}] {message}")

    def _handle_session_refresh_completed(self, division_code: str, result: object) -> None:
        self.session_refresh_results[division_code] = "Completed"
        self.append_log(f"[{division_code}] Session refresh completed.")
        self._refresh_session_status()

    def _handle_session_refresh_failed(self, division_code: str, message: str) -> None:
        self.session_refresh_results[division_code] = f"Failed: {message}"
        self.append_log(f"[{division_code}] Session refresh failed: {message}")
        self._refresh_session_status()

    def _cleanup_session_refresh_worker(self, division_code: str) -> None:
        self.session_refresh_threads.pop(division_code, None)
        self.session_refresh_workers.pop(division_code, None)
        self.session_refresh_bridges.pop(division_code, None)
        if not self.session_refresh_threads:
            summary = ", ".join(f"{code}: {status}" for code, status in sorted(self.session_refresh_results.items()))
            self.append_log(f"All parallel session refreshes finished. {summary}")
            self._set_run_buttons_enabled(True)
            self._refresh_session_status()

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
        if event.event.startswith("session."):
            session_path = payload.get("session_path")
            if session_path:
                self.session_dir_override = Path(str(session_path)).parent
                self.append_log(f"Session file: {session_path}")
            self._refresh_session_status()
        if event.event.startswith("tab.") or event.event.startswith("row."):
            self.update_agent_progress(event.event, payload)
        if event.event.startswith("row."):
            self._update_record_from_event(event.event, payload, message)
        if event.event.startswith("duplicate."):
            self._handle_duplicate_event(event.event, payload, message)
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
        self._refresh_session_status()
        self._refresh_summary()
        self.use_last_run_employees()
        self.tabs.setCurrentIndex(2)

    def _handle_run_failed(self, message: str) -> None:
        if self.current_artifacts:
            self.artifact_store.write_result(self.current_artifacts, {"success": False, "error_summary": message})
            self.append_log(f"Failure result saved: {self.current_artifacts.result_path}")
        self.append_log(f"Runner failed: {message}")
        self._set_run_buttons_enabled(True)
        self._refresh_session_status()
        self._refresh_summary()

    def set_records(self, records: list[ManualAdjustmentRecord]) -> None:
        self.records = records
        self.records_table.setRowCount(len(records))
        self.record_status = {}
        for row, record in enumerate(records):
            key = self._record_key(record)
            self.record_status[key] = {"row": row, "input_status": "Pending", "db_status": "Not Checked", "message": ""}
            values = ["Pending", "Not Checked", self._sync_status_from_remarks(record), self._fetch_verification_display(record) or self._match_status_from_remarks(record), record.emp_code, record.gang_code, record.division_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), self._remarks_adcode(record), f"{record.amount:g}", record.remarks]
            for column, value in enumerate(values):
                self.records_table.setItem(row, column, QTableWidgetItem(value))
            self._apply_record_row_style(row, "Pending", "Not Checked")
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

    def fetch_duplicate_targets(self) -> None:
        if not self._duplicate_category_supported():
            self.duplicate_status_label.setText("Duplicate cleanup baru aktif untuk Auto Buffer.")
            return
        filters = self._parse_list(self.duplicate_filters.text())
        if not filters:
            self.duplicate_status_label.setText("Filters masih kosong.")
            return
        self.fetch_duplicates_button.setEnabled(False)
        self.delete_duplicates_button.setEnabled(False)
        self.duplicate_status_label.setText("Fetching duplicate targets...")
        self.duplicate_fetch_thread = QThread(self)
        self.duplicate_fetch_worker = DuplicateFetchWorker(self._api_client(), self.duplicate_month.value(), self.duplicate_year.value(), self._selected_division_code(), filters)
        self.duplicate_fetch_worker.moveToThread(self.duplicate_fetch_thread)
        self.duplicate_fetch_thread.started.connect(self.duplicate_fetch_worker.run)
        self.duplicate_fetch_worker.completed.connect(self._handle_duplicate_fetch_completed)
        self.duplicate_fetch_worker.failed.connect(self._handle_duplicate_fetch_failed)
        self.duplicate_fetch_worker.completed.connect(self.duplicate_fetch_thread.quit)
        self.duplicate_fetch_worker.failed.connect(self.duplicate_fetch_thread.quit)
        self.duplicate_fetch_thread.finished.connect(self.duplicate_fetch_thread.deleteLater)
        self.duplicate_fetch_thread.start()

    def _handle_duplicate_fetch_completed(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.fetch_duplicates_button.setEnabled(True)
        self.duplicate_targets = targets
        self._render_duplicate_targets(targets)
        self.delete_duplicates_button.setEnabled(bool(targets))
        self.duplicate_status_label.setText(f"Loaded {len(targets)} DELETE_OLD duplicate targets.")

    def _handle_duplicate_fetch_failed(self, message: str) -> None:
        self.fetch_duplicates_button.setEnabled(True)
        self.delete_duplicates_button.setEnabled(False)
        self.duplicate_status_label.setText(f"Fetch failed: {message}")
        self.append_log(f"Duplicate target fetch failed: {message}")

    def _render_duplicate_targets(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.duplicate_target_rows = {}
        self.duplicate_table.setRowCount(len(targets))
        for row, target in enumerate(targets):
            self.duplicate_target_rows[target.doc_id] = row
            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Checked if target.action == "DELETE_OLD" else Qt.CheckState.Unchecked)
            self.duplicate_table.setItem(row, 0, select_item)
            values = [target.action, target.doc_id, target.emp_code, target.emp_name, target.doc_desc, target.keep_doc_id, "Pending", ""]
            for column, value in enumerate(values, start=1):
                self.duplicate_table.setItem(row, column, QTableWidgetItem(str(value)))

    def run_duplicate_cleanup(self) -> None:
        if self._runner_is_active():
            self.duplicate_status_label.setText("Runner sedang berjalan.")
            return
        if not self._duplicate_category_supported():
            self.duplicate_status_label.setText("Duplicate cleanup baru aktif untuk Auto Buffer.")
            return
        selected = self._selected_duplicate_targets()
        if not selected:
            self.duplicate_status_label.setText("Tidak ada duplicate target yang dipilih.")
            return
        if not self.duplicate_dry_run.isChecked() and self.runner_mode.currentText() != "fresh_login_single" and not self._selected_session_active():
            division_code = self._selected_division_code()
            message = f"Session aktif untuk {division_code} belum ada. Jalankan Get Session dulu atau pilih runner mode fresh_login_single."
            self.duplicate_status_label.setText(message)
            self.append_log(f"Duplicate cleanup blocked: {message}")
            QMessageBox.warning(self, "Session belum aktif", message)
            self.tabs.setCurrentIndex(0)
            return
        if not self.duplicate_dry_run.isChecked():
            answer = QMessageBox.question(self, "Confirm Duplicate Delete", f"Delete {len(selected)} duplicate DocIDs from {self._selected_division_code()}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.duplicate_status_label.setText("Actual delete dibatalkan.")
                return
        self.duplicate_status_label.setText(f"Starting duplicate cleanup for {len(selected)} DocIDs...")
        self.append_log(f"Duplicate cleanup selected targets: {[(target.doc_id, target.master_id) for target in selected[:10]]}")
        payload = self.build_payload(mode=self.runner_mode.currentText(), records=[])
        payload = RunPayload(
            period_month=self.duplicate_month.value(),
            period_year=self.duplicate_year.value(),
            division_code=self._selected_division_code(),
            gang_code=payload.gang_code,
            emp_code=payload.emp_code,
            adjustment_type=payload.adjustment_type,
            adjustment_name=payload.adjustment_name,
            category_key=payload.category_key,
            runner_mode=payload.runner_mode,
            max_tabs=payload.max_tabs,
            headless=payload.headless,
            only_missing_rows=payload.only_missing_rows,
            row_limit=payload.row_limit,
            records=[],
            operation="delete_duplicates",
            duplicate_targets=selected,
            delete_dry_run=self.duplicate_dry_run.isChecked(),
        )
        self.start_runner(payload, f"Starting duplicate cleanup for {len(selected)} DocIDs...")
        self.tabs.setCurrentIndex(1)

    def _selected_duplicate_targets(self) -> list[DuplicateDocIdTarget]:
        selected: list[DuplicateDocIdTarget] = []
        for row, target in enumerate(self.duplicate_targets):
            item = self.duplicate_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked and target.action == "DELETE_OLD":
                selected.append(target)
        return selected

    def _handle_duplicate_event(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        doc_id = str(payload.get("doc_id", ""))
        row = self.duplicate_target_rows.get(doc_id)
        if row is not None:
            status = str(payload.get("status") or event_name.rsplit(".", 1)[-1])
            self.duplicate_table.setItem(row, 7, QTableWidgetItem(status))
            self.duplicate_table.setItem(row, 8, QTableWidgetItem(message))
        counts = {"deleted": 0, "dry_run": 0, "not_found": 0, "failed": 0}
        for row_index in range(self.duplicate_table.rowCount()):
            status_item = self.duplicate_table.item(row_index, 7)
            status = status_item.text() if status_item else ""
            if status in counts:
                counts[status] += 1
        self.duplicate_status_label.setText(f"Deleted: {counts['deleted']} | Dry-run: {counts['dry_run']} | Not found: {counts['not_found']} | Failed: {counts['failed']}")
        self._append_event_row(event_name, payload, message)

    def _duplicate_category_supported(self) -> bool:
        return str(self.category.currentData() or "") in {"spsi", "masa_kerja", "tunjangan_jabatan"}

    def _update_record_from_event(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        record = self._find_record(str(payload.get("emp_code", "")), str(payload.get("adjustment_name", "")))
        if not record:
            return
        key = self._record_key(record)
        row = int(self.record_status.get(key, {}).get("row", -1))
        if row < 0:
            return
        status_map = {"row.started": "Running", "row.success": "Input Done", "row.skipped": "Skipped", "row.failed": "Failed"}
        status = status_map.get(event_name, event_name)
        self.record_status[key].update({"input_status": status, "message": message, "tab_index": payload.get("tab_index")})
        self.records_table.setItem(row, 0, QTableWidgetItem(status))
        self._apply_record_row_style(row, status, str(self.record_status[key].get("db_status", "Not Checked")))
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
            input_status = str(state.get("input_status", "Pending"))
            db_status = str(state.get("db_status", "Not Checked"))
            if input_status == "Input Done":
                success_records.append(record)
            elif input_status == "Failed":
                failed_records.append(record)
            table_rows.append([input_status, db_status, self._sync_status_from_remarks(record), self._match_status_from_remarks(record), record.emp_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), f"{record.amount:g}", str(state.get("message", "")), str(state.get("tab_index", ""))])
        self.last_successful_records = success_records
        attempted = len([row for row in table_rows if row[0] in {"Input Done", "Skipped", "Failed"}])
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

    def _apply_record_row_style(self, row: int, input_status: str, db_status: str) -> None:
        from PySide6.QtGui import QColor
        theme = AppTheme
        if input_status == "Input Done":
            background_color = QColor(theme.STATUS_SUCCESS)
            foreground_color = QColor(theme.TEXT_PRIMARY)
        elif input_status == "Skipped":
            background_color = QColor(theme.STATUS_INFO)
            foreground_color = QColor(theme.TEXT_PRIMARY)
        elif input_status == "Failed" or db_status == "DB Mismatch":
            background_color = QColor(theme.STATUS_ERROR)
            foreground_color = QColor(theme.TEXT_PRIMARY)
        elif db_status == "Already in DB":
            background_color = QColor(theme.PRIMARY)
            foreground_color = QColor(theme.TEXT_PRIMARY)
        else:
            return
        for column in range(self.records_table.columnCount()):
            item = self.records_table.item(row, column)
            if item:
                item.setBackground(background_color)
                item.setForeground(foreground_color)

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

    def _session_dir(self) -> Path:
        if self.session_dir_override is not None:
            return self.session_dir_override
        for part in self.config.runner_command.replace("\\", "/").split():
            path = Path(part.strip('"'))
            if "runner" in path.parts:
                runner_parts = path.parts[: path.parts.index("runner") + 1]
                return Path(*runner_parts) / "data" / "sessions"
        return Path("runner") / "data" / "sessions"

    def _scan_session_status(self) -> list[dict[str, str | bool]]:
        now = datetime.now(timezone.utc)
        session_dir = self._session_dir()
        division_options = self.divisions or [DivisionOption(self.config.default_division_code, self.config.default_division_code)]
        results: list[dict[str, str | bool]] = []
        for division in division_options:
            code = division.code.strip().upper()
            session_file = session_dir / f"session-{code}.json"
            status = "— None"
            age = ""
            saved = ""
            active = False
            if session_file.exists():
                try:
                    data = json.loads(session_file.read_text(encoding="utf-8"))
                    saved_at = self._parse_session_timestamp(str(data.get("savedAt", "")))
                    file_division = str(data.get("division") or code).strip().upper()
                    age_minutes = int((now - saved_at).total_seconds() / 60)
                    active = file_division == code and age_minutes < 240
                    if file_division != code:
                        status = f"Mismatch ({file_division})"
                    else:
                        status = "Active" if active else "Expired"
                    age = f"{age_minutes}m"
                    saved = saved_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                except (OSError, json.JSONDecodeError, ValueError):
                    status = "Invalid"
            results.append({"code": code, "label": division.label, "status": status, "age": age, "saved": saved, "active": active})
        return results

    def _parse_session_timestamp(self, value: str) -> datetime:
        if not value:
            raise ValueError("missing savedAt")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _selected_session_status(self) -> dict[str, str | bool] | None:
        selected_code = self._selected_division_code()
        return next((item for item in self._scan_session_status() if item["code"] == selected_code), None)

    def _runner_is_active(self) -> bool:
        if not self.run_thread:
            return False
        try:
            return self.run_thread.isRunning()
        except RuntimeError:
            self.run_thread = None
            self.run_worker = None
            self.runner_bridge = None
            return False

    def _selected_session_active(self) -> bool:
        status = self._selected_session_status()
        return bool(status and status["active"])

    def _refresh_session_status(self) -> None:
        from PySide6.QtGui import QColor
        if not hasattr(self, "session_table"):
            return
        selected_code = self._selected_division_code()
        rows = self._scan_session_status()
        self.session_table.setRowCount(len(rows))
        selected_status: dict[str, str | bool] | None = None
        highlight_color = QColor(AppTheme.PRIMARY)
        text_color = QColor(AppTheme.TEXT_PRIMARY)
        for row, item in enumerate(rows):
            if item["code"] == selected_code:
                selected_status = item
            values = [str(item["code"]), str(item["label"]), str(item["status"]), str(item["age"]), str(item["saved"])]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if item["code"] == selected_code:
                    table_item.setBackground(highlight_color)
                    table_item.setForeground(text_color)
                self.session_table.setItem(row, column, table_item)
            button = QPushButton("Get Session")
            button.clicked.connect(lambda checked=False, code=str(item["code"]): self.get_session_for_division(code))
            self.session_table.setCellWidget(row, 5, button)
        if selected_status and selected_status["active"]:
            self.session_status_label.setText(f"Session ready for {selected_code} (age: {selected_status['age']})")
        else:
            self.session_status_label.setText(f"No active session for {selected_code}. Use Get Session or runner will do fresh login.")

    def _description_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        if record.adjustment_type == "AUTO_BUFFER" and category and category.description:
            return category.description
        name = record.adjustment_name.strip()
        return name[5:] if name.upper().startswith("AUTO ") else name

    def _adcode_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        is_auto_buffer = record.adjustment_type == "AUTO_BUFFER" or (record.category_key or "") in {"spsi", "masa_kerja", "tunjangan_jabatan"}
        if is_auto_buffer and category and category.adcode:
            return category.adcode
        if record.ad_code:
            return record.ad_code
        remarks_adcode = self._remarks_adcode(record)
        if remarks_adcode:
            return remarks_adcode
        if category and category.adcode:
            return category.adcode
        return self._description_for_record(record).lower()

    def _remarks_parts(self, record: ManualAdjustmentRecord) -> list[str]:
        return remarks_parts(record)

    def _remarks_adcode(self, record: ManualAdjustmentRecord) -> str:
        explicit_adcode = extract_ad_code_from_remarks(record.remarks)
        if explicit_adcode:
            return explicit_adcode
        parts = self._remarks_parts(record)
        return parts[1] if len(parts) >= 2 else ""

    def _remarks_token(self, record: ManualAdjustmentRecord, key: str) -> str:
        return remarks_token(record, key)

    def _sync_status_from_remarks(self, record: ManualAdjustmentRecord) -> str:
        return sync_status_from_remarks(record)

    def _match_status_from_remarks(self, record: ManualAdjustmentRecord) -> str:
        return match_status_from_remarks(record)

    def _fetch_verification_display(self, record: ManualAdjustmentRecord) -> str:
        status = self.fetch_verification_status.get((record.emp_code, self._filter_for_record(record)), {})
        return str(status.get("status") or "")

    def _record_is_miss(self, record: ManualAdjustmentRecord) -> bool:
        verified_status = self._fetch_verification_display(record).upper()
        if verified_status in {"VERIFIED_MATCH", "VERIFIED_MISMATCH"}:
            return False
        if verified_status == "VERIFIED_NOT_FOUND":
            return True
        return record_is_stale_miss(record)

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
            db_status = str(self.record_status.get(key, {}).get("db_status", "Not Checked"))
            self.record_status[key] = {"row": row, "input_status": "Pending", "db_status": db_status, "message": ""}
            if row >= 0:
                self.records_table.setItem(row, 0, QTableWidgetItem("Pending"))
                self.records_table.setItem(row, 1, QTableWidgetItem(db_status))
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
        self.refresh_sessions_button.setEnabled(enabled)
        self.refresh_all_sessions_button.setEnabled(enabled)
        self.session_table.setEnabled(enabled)
        if hasattr(self, "fetch_duplicates_button"):
            self.fetch_duplicates_button.setEnabled(enabled)
        if hasattr(self, "delete_duplicates_button"):
            self.delete_duplicates_button.setEnabled(enabled and bool(self.duplicate_targets))
        self.stop_button.setEnabled(not enabled)
        if enabled and hasattr(self, "progress_bar"):
            self.progress_bar.setVisible(False)
            self.status_bar.showMessage("Ready")

    def _update_process_context(self) -> None:
        if not hasattr(self, "process_context_label"):
            return
        limit_text = "No limit" if self.row_limit.value() == 0 else str(self.row_limit.value())
        miss_filter = "MISS-only ON" if self.process_only_miss.isChecked() else "MISS-only OFF"
        self.process_context_label.setText(f"Fetched: {len(self.records)} | Category: {self.category.currentText()} | Row limit: {limit_text} | {miss_filter}")

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
            "potongan_upah_bersih": "potongan upah bersih",
            "premi_tunjangan": "premi",
        }
        default_filter = defaults.get(category_key, category_key or "spsi")
        self.verify_filters.setText(default_filter)
        if hasattr(self, "duplicate_filters"):
            self.duplicate_month.setValue(self.period_month.value())
            self.duplicate_year.setValue(self.period_year.value())
            self.duplicate_filters.setText(default_filter)

    def _parse_list(self, value: str) -> list[str]:
        return [item.strip() for chunk in value.splitlines() for item in chunk.split(",") if item.strip()]

    def _filter_for_record(self, record: ManualAdjustmentRecord) -> str:
        return filter_for_record(record)

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

    def _on_division_monitor_run(self, division_code: str, cat_key: str, cat_label: str, mode: str, month: int, year: int, extra_details: object | None = None) -> None:
        from app.ui.division_run_dialog import DivisionRunDialog
        division_label = next((d.label for d in self.divisions if d.code == division_code), division_code)
        dialog = DivisionRunDialog(
            config=self.config,
            categories=self.categories,
            api_client=self._api_client(),
            division_code=division_code,
            division_label=division_label,
            category_key=cat_key,
            category_label=cat_label,
            mode=mode,
            month=month,
            year=year,
            extra_details=extra_details if isinstance(extra_details, list) else None,
            parent=self,
        )
        self.division_run_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self.division_run_dialogs.remove(d) if d in self.division_run_dialogs else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def append_log(self, message: str) -> None:
        self.log_output.append(message)
