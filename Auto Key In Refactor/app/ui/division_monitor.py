"""Division monitor — compares manual adjustment (expected) vs db_ptrj actual (check-adtrans).

Source of truth is db_ptrj via check_adtrans_report(division_code=...), NOT remarks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.category_registry import CategoryRegistry
from app.ui.themes import AppTheme

CATEGORY_TO_FILTER = {
    "spsi": "spsi",
    "masa_kerja": "masa kerja",
    "tunjangan_jabatan": "jabatan",
    "premi": "premi",
    "potongan_upah_kotor": "potongan",
    "premi_tunjangan": "premi",
}


@dataclass
class CategoryStatus:
    total: int = 0
    match: int = 0
    mismatch: int = 0
    miss: int = 0
    match_amount: float = 0.0
    mismatch_amount: float = 0.0
    miss_amount: float = 0.0


@dataclass
class DivisionSummary:
    division_code: str
    division_label: str
    categories: dict[str, CategoryStatus] = field(default_factory=dict)


class DivisionMonitorWorker(QObject):
    progress = Signal(str, int, int)
    division_done = Signal(str, object)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        period_month: int,
        period_year: int,
        division_codes: list[str],
        category_keys: list[str],
    ) -> None:
        super().__init__()
        self.client = client
        self.period_month = period_month
        self.period_year = period_year
        self.division_codes = division_codes
        self.category_keys = category_keys

    def run(self) -> None:
        try:
            summaries: list[DivisionSummary] = []
            for index, code in enumerate(self.division_codes):
                self.progress.emit(code, index + 1, len(self.division_codes))
                summary = self._process_division(code)
                summaries.append(summary)
                self.division_done.emit(code, summary)
            self.completed.emit(summaries)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _process_division(self, division_code: str) -> DivisionSummary:
        # 1) Get expected amounts from manual adjustment API
        query = ManualAdjustmentQuery(
            period_month=self.period_month,
            period_year=self.period_year,
            division_code=division_code,
        )
        records = self.client.get_adjustments(query)

        # Build expected: (emp_code, filter_name) -> total expected amount per category
        expected: dict[tuple[str, str], float] = {}
        for record in records:
            cat_key = record.category_key or "unknown"
            filter_name = CATEGORY_TO_FILTER.get(cat_key, cat_key)
            key = (record.emp_code, filter_name)
            expected[key] = expected.get(key, 0.0) + record.amount

        # 2) Get actual from db_ptrj via check_adtrans_report(division_code=...)
        filters = sorted({CATEGORY_TO_FILTER.get(k, k) for k in self.category_keys})
        actual_data: list[dict[str, Any]] = []
        try:
            report = self.client.check_adtrans_report(
                self.period_month, self.period_year,
                filters,
                division_code=division_code,
            )
            data = report.get("data", [])
            if isinstance(data, dict):
                data = data.get("data", [])
            if isinstance(data, list):
                actual_data = [item for item in data if isinstance(item, dict)]
        except Exception:
            pass

        # Build actual lookup: (emp_code, filter_name) -> actual value from db_ptrj
        actual: dict[tuple[str, str], float] = {}
        for item in actual_data:
            emp_code = str(
                item.get("emp_code") or item.get("EmpCode") or ""
            ).upper().strip()
            for filter_name in filters:
                val = item.get(filter_name)
                if val is not None:
                    try:
                        actual[(emp_code, filter_name)] = float(val)
                    except (TypeError, ValueError):
                        pass

        # 3) Compare expected vs actual per (emp_code, category)
        #    Status determined DIRECTLY from db_ptrj, not from remarks
        cats: dict[str, CategoryStatus] = {}
        for (emp_code, filter_name), expected_amount in expected.items():
            # Find category key from filter_name
            cat_key = filter_name
            for ck, fn in CATEGORY_TO_FILTER.items():
                if fn == filter_name:
                    cat_key = ck
                    break

            if cat_key not in cats:
                cats[cat_key] = CategoryStatus()
            cats[cat_key].total += 1

            actual_amount = actual.get((emp_code, filter_name), 0.0)
            if actual_amount == expected_amount and actual_amount != 0.0:
                cats[cat_key].match += 1
                cats[cat_key].match_amount += actual_amount
            elif actual_amount != 0.0:
                cats[cat_key].mismatch += 1
                cats[cat_key].mismatch_amount += abs(expected_amount - actual_amount)
            else:
                cats[cat_key].miss += 1
                cats[cat_key].miss_amount += expected_amount

        return DivisionSummary(
            division_code=division_code,
            division_label=division_code,
            categories=cats,
        )


class DivisionMonitorWidget(QWidget):
    def __init__(
        self,
        api_client_factory: Any,
        categories: CategoryRegistry,
        divisions: list[Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_client_factory = api_client_factory
        self.categories = categories
        self.divisions = divisions or []
        self.summaries: list[DivisionSummary] = []
        self._thread: QThread | None = None
        self._worker: DivisionMonitorWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # Controls
        ctrl = QHBoxLayout()
        ctrl_form = QFormLayout()
        self.mon_month = QSpinBox()
        self.mon_month.setRange(1, 12)
        self.mon_month.setValue(4)
        self.mon_year = QSpinBox()
        self.mon_year.setRange(2000, 2100)
        self.mon_year.setValue(2026)
        ctrl_form.addRow("Period Month", self.mon_month)
        ctrl_form.addRow("Period Year", self.mon_year)
        ctrl.addLayout(ctrl_form)
        self.refresh_btn = QPushButton("Refresh All Divisions")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(self._refresh_all)
        ctrl.addWidget(self.refresh_btn)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet("color: #94a3b8; font-weight: 500;")
        ctrl.addWidget(self.status_lbl, 1)
        layout.addLayout(ctrl)

        # Category summary cards
        card_grid = QGridLayout()
        card_grid.setSpacing(10)
        self._card_widgets: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for idx, cat in enumerate(self.categories.categories):
            grp = QWidget()
            grp.setStyleSheet(AppTheme.get_card_stylesheet(AppTheme.PRIMARY))
            v = QVBoxLayout(grp)
            v.setSpacing(4)
            v.setContentsMargins(12, 12, 12, 12)
            title = QLabel(cat.label.upper())
            title.setObjectName("card-title")
            total = QLabel("0")
            total.setObjectName("card-value")
            miss = QLabel("Miss: 0")
            miss.setStyleSheet(f"color: {AppTheme.STATUS_ERROR}; font-weight: 600;")
            mismatch = QLabel("Mismatch: 0")
            mismatch.setStyleSheet(f"color: {AppTheme.STATUS_WARNING}; font-weight: 600;")
            v.addWidget(title)
            v.addWidget(total)
            v.addWidget(miss)
            v.addWidget(mismatch)
            self._card_widgets[cat.key] = (total, miss, mismatch)
            card_grid.addWidget(grp, idx // 3, idx % 3)
        layout.addLayout(card_grid)

        # Detail table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Division", "Category", "Total", "Match (DB)", "Mismatch (DB)", "Miss (DB)", "Miss Amount", "Mismatch Amount"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

    def _is_running(self) -> bool:
        if self._thread is None:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
            self._thread = None
            self._worker = None
            return False

    def _refresh_all(self) -> None:
        if self._is_running():
            return
        codes = [d.code for d in self.divisions] if self.divisions else ["P1B"]
        cat_keys = [c.key for c in self.categories.categories]
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText(f"Fetching {len(codes)} divisions from db_ptrj...")
        self.table.setRowCount(0)
        self.summaries = []
        for total, miss, mismatch in self._card_widgets.values():
            total.setText("0")
            miss.setText("Miss: 0")
            mismatch.setText("Mismatch: 0")
        client = self.api_client_factory()
        self._thread = QThread(self)
        self._worker = DivisionMonitorWorker(
            client, self.mon_month.value(), self.mon_year.value(), codes, cat_keys
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.division_done.connect(self._on_division_done)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _on_progress(self, code: str, current: int, total: int) -> None:
        self.status_lbl.setText(f"Checking db_ptrj for {code}... ({current}/{total})")

    def _on_division_done(self, code: str, summary: DivisionSummary) -> None:
        self.summaries.append(summary)
        self._render_table()
        self._update_cards()

    def _on_completed(self, summaries: list[DivisionSummary]) -> None:
        self.summaries = summaries
        self.refresh_btn.setEnabled(True)
        total_miss = sum(
            s.categories.get(k, CategoryStatus()).miss
            for s in summaries
            for k in s.categories
        )
        total_mismatch = sum(
            s.categories.get(k, CategoryStatus()).mismatch
            for s in summaries
            for k in s.categories
        )
        self.status_lbl.setText(
            f"Done. Total miss (db_ptrj): {total_miss}, mismatch (db_ptrj): {total_mismatch}"
        )
        self._render_table()
        self._update_cards()

    def _on_failed(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_lbl.setText(f"Error: {message}")

    def _update_cards(self) -> None:
        for key, (total_lbl, miss_lbl, mismatch_lbl) in self._card_widgets.items():
            total = sum(s.categories.get(key, CategoryStatus()).total for s in self.summaries)
            miss = sum(s.categories.get(key, CategoryStatus()).miss for s in self.summaries)
            mismatch = sum(s.categories.get(key, CategoryStatus()).mismatch for s in self.summaries)
            total_lbl.setText(str(total))
            miss_lbl.setText(f"Miss: {miss}")
            mismatch_lbl.setText(f"Mismatch: {mismatch}")

    def _render_table(self) -> None:
        rows: list[list[str]] = []
        for summary in self.summaries:
            for key in sorted(summary.categories.keys()):
                cat = summary.categories[key]
                cat_label = next(
                    (c.label for c in self.categories.categories if c.key == key), key
                )
                rows.append([
                    summary.division_code,
                    cat_label,
                    str(cat.total),
                    str(cat.match),
                    str(cat.mismatch),
                    str(cat.miss),
                    f"{cat.miss_amount:,.0f}",
                    f"{cat.mismatch_amount:,.0f}",
                ])
        self.table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c == 5 and value != "0":
                    item.setForeground(QColor(AppTheme.STATUS_ERROR))
                if c == 4 and value != "0":
                    item.setForeground(QColor(AppTheme.STATUS_WARNING))
                if c == 3 and value != "0":
                    item.setForeground(QColor(AppTheme.STATUS_SUCCESS))
                self.table.setItem(r, c, item)

