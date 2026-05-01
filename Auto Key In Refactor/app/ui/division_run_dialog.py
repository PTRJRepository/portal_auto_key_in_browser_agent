"""Division Run Dialog — standalone window for running auto key-in per division+category."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.category_registry import CategoryRegistry
from app.core.config import AppConfig
from app.core.models import ManualAdjustmentRecord, RunPayload, enrich_records_with_automation_options
from app.core.run_service import filter_by_category
from app.core.runner_bridge import RunnerBridge, RunnerEvent
from app.ui.themes import AppTheme

def automation_option_categories_for_records(records: list[ManualAdjustmentRecord]) -> list[str]:
    category_by_type = {
        "PREMI": "premi",
        "POTONGAN_KOTOR": "koreksi",
        "POTONGAN_BERSIH": "potongan_upah_bersih",
    }
    categories: list[str] = []
    for record in records:
        category = category_by_type.get(record.adjustment_type)
        if category and category not in categories:
            categories.append(category)
    return categories


class DivisionFetchWorker:
    """Fetch records for a specific division+category."""

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        month: int,
        year: int,
        division_code: str,
        category_key: str,
        adjustment_type: str | None,
        adjustment_name: str | None,
    ) -> None:
        self.client = client
        self.month = month
        self.year = year
        self.division_code = division_code
        self.category_key = category_key
        self.adjustment_type = adjustment_type
        self.adjustment_name = adjustment_name

    def run(self) -> list[ManualAdjustmentRecord]:
        query = ManualAdjustmentQuery(
            period_month=self.month,
            period_year=self.year,
            division_code=self.division_code,
            adjustment_type=self.adjustment_type,
            adjustment_name=self.adjustment_name,
        )
        if self.category_key in {"premi", "premi_tunjangan"} or query.requests_premium():
            query = query.with_grouped_premium_details()
        records = self.client.get_adjustments(query)
        records = self._enrich_manual_automation_details(records, query)
        return filter_by_category(records, self.category_key)

    def _enrich_manual_automation_details(
        self,
        records: list[ManualAdjustmentRecord],
        query: ManualAdjustmentQuery,
    ) -> list[ManualAdjustmentRecord]:
        needs_detail = [
            record for record in records
            if record.adjustment_type in {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH"} and not (record.ad_code and record.task_code and record.task_desc)
        ]
        if not needs_detail:
            return records
        try:
            categories = automation_option_categories_for_records(needs_detail)
            if not categories:
                return records
            options = self.client.get_automation_options(
                division_code=self.division_code,
                categories=categories,
                limit=200,
            )
            if not isinstance(options, list):
                return records
            return enrich_records_with_automation_options(records, options)
        except Exception:
            return records


class DivisionRunDialog(QDialog):
    """Standalone dialog that runs get_session + fetch + auto key-in for one division+category."""

    log_message = Signal(str)
    run_completed = Signal()
    run_failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        categories: CategoryRegistry,
        api_client: ManualAdjustmentApiClient,
        division_code: str,
        division_label: str,
        category_key: str,
        category_label: str,
        mode: str,
        month: int,
        year: int,
        extra_details: list[Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.categories = categories
        self.api_client = api_client
        self.division_code = division_code
        self.division_label = division_label
        self.category_key = category_key
        self.category_label = category_label
        self.mode = mode
        self.month = month
        self.year = year
        self.extra_details = list(extra_details or [])
        self.records: list[ManualAdjustmentRecord] = []
        self.setWindowTitle(f"Run {division_code} / {category_label}")
        self.resize(900, 650)
        self.setStyleSheet(AppTheme.get_stylesheet())
        self._build_ui()
        self._threads: list[QThread] = []
        self._workers: list[Any] = []
        self._runner_bridge: RunnerBridge | None = None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        self.title_lbl = QLabel(
            f"<b>{self.division_code}</b> — {self.division_label}  |  "
            f"<b>{self.category_label}</b>  |  "
            f"Period: {self.month}/{self.year}"
        )
        self.title_lbl.setStyleSheet("font-size: 16px;")
        header.addWidget(self.title_lbl)
        header.addStretch(1)
        self.status_lbl = QLabel("Idle")
        self.status_lbl.setStyleSheet(f"color: {AppTheme.TEXT_SECONDARY}; font-weight: 500;")
        header.addWidget(self.status_lbl)
        layout.addLayout(header)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(6)
        layout.addWidget(self.progress)

        # Live record table
        self.record_table = QTableWidget(0, 5)
        self.record_table.setHorizontalHeaderLabels(["Emp Code", "Gang", "Adjustment", "Amount", "Status"])
        self.record_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.record_table, 2)

        # Log
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(180)
        layout.addWidget(self.log_output)

        # Buttons
        btns = QHBoxLayout()
        self.sync_btn = QPushButton("Sync Missing")
        self.sync_btn.setObjectName("primary")
        self.sync_btn.setToolTip("Sync missing records from db_ptrj to extend_db via API")
        self.sync_btn.clicked.connect(self._on_sync_missing)

        self.run_btn = QPushButton("Run Auto Key-In")
        self.run_btn.setObjectName("success")
        self.run_btn.clicked.connect(self._start_workflow)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._on_close)
        btns.addWidget(self.sync_btn)
        btns.addWidget(self.run_btn)
        btns.addStretch(1)
        btns.addWidget(self.close_btn)
        layout.addLayout(btns)

        self.log_message.connect(self._append_log)
        self.run_completed.connect(self._on_run_completed)
        self.run_failed.connect(self._on_run_failed)

    def _append_log(self, message: str) -> None:
        self.log_output.append(message)

    def _set_status(self, text: str) -> None:
        self.status_lbl.setText(text)
        self._append_log(text)

    def _on_sync_missing(self) -> None:
        self.sync_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._set_status("Syncing missing records from db_ptrj...")

        try:
            cat = self.categories.by_key(self.category_key)
            filters = None
            if cat:
                # Map category key to filter name for sync endpoint
                filter_map = {
                    "spsi": ["spsi"],
                    "masa_kerja": ["masa kerja"],
                    "tunjangan_jabatan": ["jabatan"],
                    "premi": ["premi"],
                    "potongan_upah_kotor": ["koreksi", "potongan"],
                    "potongan_upah_bersih": ["potongan upah bersih"],
                    "premi_tunjangan": ["tunjangan premi"],
                }
                filters = filter_map.get(self.category_key)

            result = self.api_client.sync_adtrans(
                self.month,
                self.year,
                self.division_code,
                filters=filters,
                sync_mode="MISMATCH_AND_MISSING",
            )
            data = result.get("data", {})
            synced = data.get("synced_count", 0) if isinstance(data, dict) else 0
            skipped = data.get("skipped_match", 0) if isinstance(data, dict) else 0
            self._set_status(f"Sync done. Inserted/updated: {synced}, Skipped (match): {skipped}")
            self._append_log(f"Sync result: {result.get('message', 'OK')}")
            QMessageBox.information(
                self, "Sync Complete",
                f"Division: {self.division_code}\nCategory: {self.category_label}\n\n"
                f"Synced: {synced} records\nSkipped: {skipped} (already match)"
            )
        except Exception as exc:
            self._append_log(f"Sync failed: {exc}")
            QMessageBox.critical(self, "Sync Failed", str(exc))
        finally:
            self.progress.setVisible(False)
            self.sync_btn.setEnabled(True)

    def _start_workflow(self) -> None:
        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._set_status("Step 1/3: Fetching records...")

        try:
            adjustment_type = None
            adjustment_name = None
            cat = self.categories.by_key(self.category_key)
            if cat and cat.adjustment_type:
                adjustment_type = cat.adjustment_type
            if self.category_key == "spsi":
                adjustment_name = "AUTO SPSI"
            elif self.category_key == "masa_kerja":
                adjustment_name = "AUTO MASA KERJA"
            elif self.category_key == "tunjangan_jabatan":
                adjustment_name = "AUTO TUNJANGAN JABATAN"

            fetcher = DivisionFetchWorker(
                self.api_client, self.month, self.year,
                self.division_code, self.category_key,
                adjustment_type, adjustment_name,
            )
            self.records = fetcher.run()
            self.records = self._filter_extra_records(self.records)
            self._append_log(f"Fetched {len(self.records)} records.")
            self._render_records()

            if not self.records:
                self._set_status("No records found. Done.")
                self.progress.setVisible(False)
                self.run_btn.setEnabled(True)
                return

            self._set_status("Step 2/3: Checking session...")
            # Simple session check: try get_session first if mode requires it
            if self.mode not in {"dry_run", "mock", "fresh_login_single"}:
                payload = self._build_payload("get_session", [])
                self._run_in_thread(payload, self._on_session_done)
            else:
                self._on_session_done(None)

        except Exception as exc:
            self._on_run_failed(str(exc))

    def _filter_extra_records(self, records: list[ManualAdjustmentRecord]) -> list[ManualAdjustmentRecord]:
        if not self.extra_details:
            return records
        detail_keys: set[tuple[str, str]] = set()
        emp_only: set[str] = set()
        for detail in self.extra_details:
            emp_code = self._detail_text(detail, "emp_code").upper()
            adjustment_name = self._detail_text(detail, "adjustment_name").upper()
            if not emp_code:
                continue
            if adjustment_name:
                detail_keys.add((emp_code, adjustment_name))
            else:
                emp_only.add(emp_code)
        if not detail_keys and not emp_only:
            return records
        return [
            record for record in records
            if (record.emp_code, record.adjustment_name.upper()) in detail_keys
            or record.emp_code in emp_only
        ]

    def _detail_text(self, detail: Any, name: str) -> str:
        if isinstance(detail, dict):
            value = detail.get(name)
        else:
            value = getattr(detail, name, "")
        return "" if value is None else str(value).strip()

    def _on_session_done(self, _result: object | None) -> None:
        self._set_status("Step 3/3: Running auto key-in...")
        payload = self._build_payload(self.mode, self.records)
        self._run_in_thread(payload, self._on_run_finished)

    def _build_payload(self, mode: str, records: list[ManualAdjustmentRecord]) -> RunPayload:
        adjustment_type = None
        adjustment_name = None
        cat = self.categories.by_key(self.category_key)
        if cat and cat.adjustment_type:
            adjustment_type = cat.adjustment_type
        if self.category_key == "spsi":
            adjustment_name = "AUTO SPSI"
        elif self.category_key == "masa_kerja":
            adjustment_name = "AUTO MASA KERJA"
        elif self.category_key == "tunjangan_jabatan":
            adjustment_name = "AUTO TUNJANGAN JABATAN"

        return RunPayload(
            period_month=self.month,
            period_year=self.year,
            division_code=self.division_code,
            gang_code=None,
            emp_code=None,
            adjustment_type=adjustment_type,
            adjustment_name=adjustment_name,
            category_key=self.category_key,
            runner_mode=mode,
            max_tabs=self.config.default_max_tabs,
            headless=self.config.headless,
            only_missing_rows=True,
            row_limit=None,
            records=records,
        )

    def _run_in_thread(self, payload: RunPayload, on_completed: Any) -> None:
        from PySide6.QtCore import QObject, Signal

        class Worker(QObject):
            completed = Signal(object)
            failed = Signal(str)
            event_received = Signal(object)

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

        bridge = RunnerBridge(self.config.runner_command)
        self._runner_bridge = bridge
        thread = QThread(self)
        worker = Worker(bridge, payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(self._handle_runner_event)
        worker.completed.connect(on_completed)
        worker.failed.connect(self.run_failed.emit)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    def _handle_runner_event(self, event: RunnerEvent) -> None:
        message = str(event.payload.get("message") or event.event)
        self.log_message.emit(message)
        if event.event.startswith("row."):
            self._update_record_status(event.event, event.payload)

    def _update_record_status(self, event_name: str, payload: dict[str, Any]) -> None:
        emp_code = str(payload.get("emp_code", ""))
        status_map = {
            "row.started": "Running",
            "row.success": "Done",
            "row.skipped": "Skipped",
            "row.failed": "Failed",
        }
        status = status_map.get(event_name, event_name)
        for row in range(self.record_table.rowCount()):
            item = self.record_table.item(row, 0)
            if item and item.text() == emp_code:
                self.record_table.setItem(row, 4, QTableWidgetItem(status))
                if status == "Done":
                    self.record_table.item(row, 4).setForeground(
                        QColor(AppTheme.STATUS_SUCCESS)
                    )
                elif status == "Failed":
                    self.record_table.item(row, 4).setForeground(
                        QColor(AppTheme.STATUS_ERROR)
                    )
                break

    def _render_records(self) -> None:
        self.record_table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            self.record_table.setItem(row, 0, QTableWidgetItem(record.emp_code))
            self.record_table.setItem(row, 1, QTableWidgetItem(record.gang_code))
            self.record_table.setItem(row, 2, QTableWidgetItem(record.adjustment_name))
            self.record_table.setItem(row, 3, QTableWidgetItem(f"{record.amount:,.0f}"))
            self.record_table.setItem(row, 4, QTableWidgetItem("Pending"))

    def _on_run_finished(self, result: object) -> None:
        self.progress.setVisible(False)
        self.run_completed.emit()
        self._set_status("Run completed.")
        self.run_btn.setEnabled(True)

    def _on_run_completed(self) -> None:
        QMessageBox.information(self, "Done", f"Run completed for {self.division_code} / {self.category_label}")

    def _on_run_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self._append_log(f"FAILED: {message}")
        self.status_lbl.setText(f"Failed: {message}")
        self.status_lbl.setStyleSheet(f"color: {AppTheme.STATUS_ERROR}; font-weight: 500;")
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Run Failed", message)

    def reject(self) -> None:
        self._stop_running_threads()
        super().reject()

    def _on_close(self) -> None:
        self.reject()

    def _stop_running_threads(self) -> None:
        if self._runner_bridge:
            self._runner_bridge.stop()
        for thread in self._threads:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass

    def closeEvent(self, event: Any) -> None:
        self._stop_running_threads()
        event.accept()
