"""Division monitor widget showing per-division, per-category status from DB."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
from app.core.models import ManualAdjustmentRecord
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
    total: int = 0; match: int = 0; mismatch: int = 0; miss: int = 0
    manual: int = 0; no_remarks: int = 0
    match_amount: float = 0.0; mismatch_amount: float = 0.0; miss_amount: float = 0.0

@dataclass
class DivisionSummary:
    division_code: str; division_label: str
    categories: dict[str, CategoryStatus] = field(default_factory=dict)


class DivisionMonitorWorker(QObject):
    progress = Signal(str, int, int)
    division_done = Signal(str, object)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, period_month: int, period_year: int, division_codes: list[str]) -> None:
        super().__init__()
        self.client = client; self.period_month = period_month; self.period_year = period_year; self.division_codes = division_codes

    def run(self) -> None:
        try:
            summaries: list[DivisionSummary] = []
            for index, code in enumerate(self.division_codes):
                self.progress.emit(code, index + 1, len(self.division_codes))
                summaries.append(self._process_division(code))
                self.division_done.emit(code, summaries[-1])
            self.completed.emit(summaries)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _process_division(self, code: str) -> DivisionSummary:
        query = ManualAdjustmentQuery(period_month=self.period_month, period_year=self.period_year, division_code=code)
        records = self.client.get_adjustments(query)
        cats: dict[str, CategoryStatus] = {}
        for record in records:
            key = record.category_key or "unknown"
            if key not in cats: cats[key] = CategoryStatus()
            cats[key].total += 1
            status = _status_from_remarks(record)
            if status == "MATCH": cats[key].match += 1; cats[key].match_amount += record.amount
            elif status == "MISMATCH": cats[key].mismatch += 1; cats[key].mismatch_amount += record.amount
            elif status in {"MISS", "MISSING"}: cats[key].miss += 1; cats[key].miss_amount += record.amount
            elif status == "MANUAL": cats[key].manual += 1
            else: cats[key].no_remarks += 1
        # Cross-check miss/mismatch with db_ptrj
        suspect = [r for r in records if _is_suspect(r)]
        if suspect:
            emp_codes = sorted({r.emp_code for r in suspect if r.emp_code})
            filters = sorted({CATEGORY_TO_FILTER.get(r.category_key or "", r.category_key or "") for r in suspect if r.category_key})
            try:
                data = self.client.check_adtrans(self.period_month, self.period_year, emp_codes, filters)
                verif = _build_verification(suspect, data)
                for r in suspect:
                    key = r.category_key or "unknown"
                    fn = CATEGORY_TO_FILTER.get(key, key)
                    v = verif.get((r.emp_code, fn), {})
                    st = str(v.get("status", ""))
                    if st == "VERIFIED_MATCH":
                        cats[key].mismatch -= 1; cats[key].mismatch_amount -= r.amount; cats[key].match += 1; cats[key].match_amount += r.amount
            except Exception:
                pass
        return DivisionSummary(division_code=code, division_label=code, categories=cats)


def _status_from_remarks(record: ManualAdjustmentRecord) -> str:
    parts = [p.strip() for p in record.remarks.split("|") if p.strip()]
    sync_val = match_val = ""
    for part in parts:
        low = part.lower()
        if low.startswith("sync:"): sync_val = part.split(":", 1)[1].strip().upper()
        elif low.startswith("match:"): match_val = part.split(":", 1)[1].strip().upper()
    if sync_val: return sync_val
    if match_val: return match_val
    if len(parts) >= 3:
        try: return "MATCH" if float(parts[2].replace(",", "")) == record.amount else "MISMATCH"
        except ValueError: return "UNKNOWN"
    if record.remarks.strip(): return "MANUAL"
    return "NO_REMARKS"

def _is_suspect(record: ManualAdjustmentRecord) -> bool:
    return _status_from_remarks(record).upper() in {"MISS", "MISSING", "MISMATCH"}

def _build_verification(records: list[ManualAdjustmentRecord], data: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    expected: dict[tuple[str, str], float] = {}
    for r in records:
        if _is_suspect(r):
            key = r.category_key or "unknown"
            expected[(r.emp_code, CATEGORY_TO_FILTER.get(key, key))] = expected.get((r.emp_code, CATEGORY_TO_FILTER.get(key, key)), 0.0) + r.amount
    actual: dict[tuple[str, str], float] = {}
    for item in data:
        ec = str(item.get("emp_code") or item.get("EmpCode") or "").upper().strip()
        for (e, f), _ in expected.items():
            if ec == e and f in item: actual[(ec, f)] = float(item.get(f, 0) or 0)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, ea in expected.items():
        aa = actual.get(key, 0.0)
        result[key] = {"status": "VERIFIED_MATCH" if aa == ea else "VERIFIED_MISMATCH" if aa else "VERIFIED_NOT_FOUND", "expected": ea, "actual": aa}
    return result


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
        self.worker: DivisionMonitorWorker | None = None
        self.thread: QThread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # Controls
        ctrl = QHBoxLayout()
        ctrl_form = QFormLayout()
        self.mon_month = QSpinBox(); self.mon_month.setRange(1, 12); self.mon_month.setValue(4)
        self.mon_year = QSpinBox(); self.mon_year.setRange(2000, 2100); self.mon_year.setValue(2026)
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
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Division", "Category", "Total", "Match", "Mismatch", "Miss", "Manual", "No Remarks", "Miss Amount"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

    def _refresh_all(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        codes = [d.code for d in self.divisions] if self.divisions else ["P1B"]
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText(f"Fetching {len(codes)} divisions...")
        self.table.setRowCount(0)
        for total, miss, mismatch in self._card_widgets.values():
            total.setText("0"); miss.setText("Miss: 0"); mismatch.setText("Mismatch: 0")
        client = self.api_client_factory()
        self.thread = QThread(self)
        self.worker = DivisionMonitorWorker(client, self.mon_month.value(), self.mon_year.value(), codes)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.division_done.connect(self._on_division_done)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _on_progress(self, code: str, current: int, total: int) -> None:
        self.status_lbl.setText(f"Fetching {code}... ({current}/{total})")

    def _on_division_done(self, code: str, summary: DivisionSummary) -> None:
        self.summaries.append(summary)
        self._render_table()
        self._update_cards()

    def _on_completed(self, summaries: list[DivisionSummary]) -> None:
        self.summaries = summaries
        self.refresh_btn.setEnabled(True)
        total_miss = sum(s.categories.get(k, CategoryStatus()).miss for s in summaries for k in s.categories)
        total_mismatch = sum(s.categories.get(k, CategoryStatus()).mismatch for s in summaries for k in s.categories)
        self.status_lbl.setText(f"Done. Total miss: {total_miss}, mismatch: {total_mismatch}")
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
                cat_label = next((c.label for c in self.categories.categories if c.key == key), key)
                rows.append([
                    summary.division_code,
                    cat_label,
                    str(cat.total),
                    str(cat.match),
                    str(cat.mismatch),
                    str(cat.miss),
                    str(cat.manual),
                    str(cat.no_remarks),
                    f"{cat.miss_amount:,.0f}",
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

