"""Division monitor — reverse comparison via reverse-compare-adtrans API."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.api_client import ManualAdjustmentApiClient
from app.core.category_registry import CategoryRegistry
from app.ui.themes import AppTheme

# Maps category key -> filter name sent to compare-adtrans API
CATEGORY_TO_FILTERS = {
    "spsi": ["spsi"],
    "masa_kerja": ["masa kerja"],
    "tunjangan_jabatan": ["jabatan"],
    "premi": ["premi"],
    "premi_tunjangan": ["tunjangan premi"],
    "potongan_upah_kotor": ["koreksi", "potongan"],
    "potongan_upah_bersih": ["potongan upah bersih"],
}

# Reverse mapping for response processing
FILTER_TO_CATEGORY: dict[str, str] = {
    "spsi": "spsi",
    "masa kerja": "masa_kerja",
    "jabatan": "tunjangan_jabatan",
    "premi": "premi",
    "tunjangan premi": "premi_tunjangan",
    "koreksi": "potongan_upah_kotor",
    "potongan": "potongan_upah_kotor",
    "potongan upah bersih": "potongan_upah_bersih",
}

DIVISION_TO_COMPARE_CODE = {
    "P1A": "PG1A",
    "P1B": "PG1B",
    "P2A": "PG2A",
    "P2B": "PG2B",
}

def filters_for_categories(category_keys: list[str]) -> list[str]:
    return sorted({filter_name for key in category_keys for filter_name in CATEGORY_TO_FILTERS.get(key, [])})


@dataclass
class MissDetail:
    emp_code: str
    gang_code: str | None
    adjustment_name: str
    source_amount: float
    category_key: str
    category_label: str
    stored_amount: float | None = None
    diff: float | None = None
    status: str = "EXTRA_IN_ADJUSTMENTS"
    division_code: str | None = None
    remarks: str | None = None
    db_doc_desc: str | None = None


@dataclass
class CategoryStatus:
    total: int = 0
    match: int = 0
    mismatch: int = 0
    missing: int = 0
    miss: int = 0
    match_amount: float = 0.0
    mismatch_amount: float = 0.0
    missing_amount: float = 0.0
    miss_amount: float = 0.0
    mismatch_details: list[MissDetail] = field(default_factory=list)
    missing_details: list[MissDetail] = field(default_factory=list)
    miss_details: list[MissDetail] = field(default_factory=list)


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
        filters = filters_for_categories(self.category_keys)
        compare_division_code = DIVISION_TO_COMPARE_CODE.get(division_code, division_code)

        compare_payload = self.client.compare_adtrans(
            self.period_month,
            self.period_year,
            compare_division_code,
            filters=filters if filters else None,
        )
        reverse_payload = self.client.reverse_compare_adtrans(
            self.period_month,
            self.period_year,
            compare_division_code,
            filters=filters if filters else None,
        )

        cats: dict[str, CategoryStatus] = {key: CategoryStatus() for key in CATEGORY_TO_FILTERS if key in self.category_keys}
        mismatch_seen: set[tuple[str, str, str]] = set()
        for item in self._comparison_items(compare_payload):
            self._apply_comparison_item(cats, item, include_match=True, mismatch_seen=mismatch_seen)
        for item in self._comparison_items(reverse_payload):
            self._apply_comparison_item(cats, item, include_match=False, mismatch_seen=mismatch_seen)

        return DivisionSummary(
            division_code=division_code,
            division_label=division_code,
            categories=cats,
        )

    def _comparison_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data", {})
        if isinstance(data, dict):
            raw_comparisons = data.get("comparisons") or data.get("items") or data.get("rows") or []
            return [item for item in raw_comparisons if isinstance(item, dict)] if isinstance(raw_comparisons, list) else []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _apply_comparison_item(
        self,
        cats: dict[str, CategoryStatus],
        item: dict[str, Any],
        include_match: bool,
        mismatch_seen: set[tuple[str, str, str]],
    ) -> None:
        status = str(item.get("status") or item.get("match_status") or item.get("comparison_status") or "").upper().strip()
        raw_category = str(item.get("category") or item.get("filter") or item.get("filter_name") or item.get("adtrans_category") or "").lower().strip()
        cat_key = FILTER_TO_CATEGORY.get(raw_category, raw_category)
        if cat_key not in CATEGORY_TO_FILTERS:
            cat_key = self.client.categories.detect(
                str(item.get("adjustment_name") or item.get("doc_desc") or ""),
                str(item.get("adjustment_type") or ""),
            ) or cat_key
        if cat_key not in cats:
            return

        cat_label = next(
            (c.label for c in self.client.categories.categories if c.key == cat_key),
            cat_key,
        )
        source_val = self._number(item, "source_amount", "sourceAmount", "db_ptrj_amount", "actual_amount", "amount")
        stored_opt = self._optional_number(item, "stored_amount", "storedAmount", "extend_db_amount", "manual_adjustment_amount", "existing_amount")
        stored_val = stored_opt or 0.0
        diff_opt = self._optional_number(item, "diff", "difference")
        diff = diff_opt if diff_opt is not None else source_val - stored_val
        detail = MissDetail(
            emp_code=str(item.get("emp_code") or item.get("EmpCode") or "").upper().strip(),
            gang_code=item.get("gang_code"),
            adjustment_name=str(item.get("adjustment_name") or item.get("doc_desc") or ""),
            source_amount=source_val,
            stored_amount=stored_opt,
            diff=diff,
            status=status,
            category_key=cat_key,
            category_label=cat_label,
            division_code=str(item.get("division_code") or "") or None,
            remarks=self._text(item, "remarks", "stored_remarks", "manual_adjustment_remarks"),
            db_doc_desc=self._text(item, "db_doc_desc", "db_ptrj_doc_desc", "source_doc_desc", "doc_desc", "docDesc", "DocDesc"),
        )
        status_key = (detail.emp_code, cat_key, detail.adjustment_name.upper())

        cats[cat_key].total += 1
        if status == "MATCH" and include_match:
            cats[cat_key].match += 1
            cats[cat_key].match_amount += stored_val
        elif status == "MISMATCH":
            if status_key in mismatch_seen:
                cats[cat_key].total -= 1
                return
            mismatch_seen.add(status_key)
            cats[cat_key].mismatch += 1
            cats[cat_key].mismatch_amount += abs(source_val - stored_val)
            cats[cat_key].mismatch_details.append(detail)
        elif status == "MISSING":
            cats[cat_key].missing += 1
            cats[cat_key].missing_amount += source_val
            cats[cat_key].missing_details.append(detail)
        elif status == "EXTRA_IN_ADJUSTMENTS":
            cats[cat_key].miss += 1
            cats[cat_key].miss_amount += stored_val
            cats[cat_key].miss_details.append(detail)
        elif not include_match:
            cats[cat_key].total -= 1

    def _number(self, item: dict[str, Any], *keys: str) -> float:
        value = self._optional_number(item, *keys)
        return value if value is not None else 0.0

    def _optional_number(self, item: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            try:
                return float(str(value).replace(",", ""))
            except (TypeError, ValueError):
                continue
        return None

    def _text(self, item: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return None


class SyncWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        month: int,
        year: int,
        division_code: str,
        filters: list[str] | None,
    ) -> None:
        super().__init__()
        self.client = client
        self.month = month
        self.year = year
        self.division_code = division_code
        self.filters = filters

    def run(self) -> None:
        try:
            result = self.client.sync_adtrans(
                self.month,
                self.year,
                self.division_code,
                filters=self.filters,
                sync_mode="MISMATCH_AND_MISSING",
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class DetailDialog(QDialog):
    """Dialog showing compare details for a division+category."""

    def __init__(
        self,
        division_code: str,
        category_label: str,
        details: list[MissDetail],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Compare Detail - {division_code} / {category_label}")
        self.resize(1180, 560)
        self.setStyleSheet(AppTheme.get_stylesheet())
        self._build_ui(details)

    def _build_ui(self, details: list[MissDetail]) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{len(details)}</b> compare issue(s)")
        header.setStyleSheet("font-size: 16px; color: #f87171; font-weight: 700;")
        layout.addWidget(header)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Status",
            "Emp Code",
            "Gang",
            "Adjustment",
            "DocDesc db_ptrj",
            "db_ptrj",
            "extend_db_ptrj",
            "Diff",
            "Remarks",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setRowCount(len(details))
        for row, d in enumerate(details):
            status_item = QTableWidgetItem(self._display_status(d.status))
            status_item.setForeground(QColor(self._status_color(d.status)))
            self.table.setItem(row, 0, status_item)
            self.table.setItem(row, 1, QTableWidgetItem(d.emp_code))
            self.table.setItem(row, 2, QTableWidgetItem(d.gang_code or "-"))
            self.table.setItem(row, 3, QTableWidgetItem(d.adjustment_name))
            self.table.setItem(row, 4, QTableWidgetItem(d.db_doc_desc or "-"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{d.source_amount:,.0f}"))
            stored_text = "-" if d.stored_amount is None else f"{d.stored_amount:,.0f}"
            self.table.setItem(row, 6, QTableWidgetItem(stored_text))
            diff = d.diff if d.diff is not None else d.source_amount - (d.stored_amount or 0.0)
            self.table.setItem(row, 7, QTableWidgetItem(f"{diff:,.0f}"))
            self.table.setItem(row, 8, QTableWidgetItem(d.remarks or "-"))
        layout.addWidget(self.table, 1)

        btns = QHBoxLayout()
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        btns.addWidget(export_btn)
        btns.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV", "extra_adjustments.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Status",
                    "Emp Code",
                    "Gang",
                    "Adjustment",
                    "DocDesc db_ptrj",
                    "db_ptrj",
                    "extend_db_ptrj",
                    "Diff",
                    "Remarks",
                ])
                for row in range(self.table.rowCount()):
                    writer.writerow([
                        self.table.item(row, 0).text(),
                        self.table.item(row, 1).text(),
                        self.table.item(row, 2).text(),
                        self.table.item(row, 3).text(),
                        self.table.item(row, 4).text(),
                        self.table.item(row, 5).text(),
                        self.table.item(row, 6).text(),
                        self.table.item(row, 7).text(),
                        self.table.item(row, 8).text(),
                    ])
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _display_status(self, status: str) -> str:
        normalized = status.upper().strip()
        if normalized == "EXTRA_IN_ADJUSTMENTS":
            return "EXTRA"
        return normalized or "-"

    def _status_color(self, status: str) -> str:
        normalized = status.upper().strip()
        if normalized == "MISMATCH":
            return AppTheme.STATUS_WARNING
        return AppTheme.STATUS_ERROR


class DivisionCard(QWidget):
    """Card widget for a single division showing per-category summaries."""

    run_requested = Signal(str, str, str, str, object)  # division_code, cat_key, cat_label, mode, extra details
    sync_requested = Signal(str, str, str)  # division_code, cat_key, cat_label
    detail_requested = Signal(str, str, list)  # division_code, cat_label, miss_details

    def __init__(
        self,
        division_code: str,
        division_label: str,
        categories: CategoryRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.division_code = division_code
        self.division_label = division_label
        self.categories = categories
        self._category_widgets: dict[str, dict[str, Any]] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._build_ui()

    def _build_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setSpacing(12)
        self.root_layout.setContentsMargins(16, 16, 16, 16)
        self.setStyleSheet(
            f"""
            DivisionCard {{
                background-color: #111827;
                border: 1px solid #475569;
                border-radius: 12px;
            }}
            QLabel#division-title {{
                font-size: 18px;
                font-weight: 700;
                color: #ffffff;
            }}
            QLabel#division-status {{
                color: #e2e8f0;
                font-weight: 600;
            }}
            QWidget#category-card {{
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 10px;
            }}
            QLabel#category-title {{
                color: #f8fafc;
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#stat-value {{
                color: #f8fafc;
                font-size: 22px;
                font-weight: 800;
            }}
            QLabel#stat-label {{
                font-size: 11px;
                color: #cbd5e1;
                font-weight: 700;
                text-transform: uppercase;
            }}
            QPushButton#run-btn {{
                background-color: #16a34a;
                color: #ffffff;
                border: 1px solid #22c55e;
                font-weight: 800;
                padding: 7px 14px;
                border-radius: 6px;
            }}
            QPushButton#run-btn:hover {{
                background-color: #22c55e;
                border-color: #4ade80;
            }}
            QPushButton#sync-btn {{
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #60a5fa;
                font-weight: 800;
                padding: 7px 14px;
                border-radius: 6px;
            }}
            QPushButton#sync-btn:hover {{
                background-color: #3b82f6;
                border-color: #93c5fd;
            }}
            QPushButton#detail-btn {{
                background-color: #334155;
                color: #f8fafc;
                font-size: 12px;
                font-weight: 700;
                padding: 6px 10px;
                border: 1px solid #64748b;
                border-radius: 6px;
            }}
            QPushButton#detail-btn:hover {{
                background-color: #475569;
                color: #ffffff;
                border-color: #94a3b8;
            }}
            QPushButton#run-btn:disabled,
            QPushButton#sync-btn:disabled,
            QPushButton#detail-btn:disabled {{
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
            }}
            """
        )

        # Header
        header = QHBoxLayout()
        title = QLabel(f"{self.division_code} — {self.division_label}")
        title.setObjectName("division-title")
        header.addWidget(title)
        header.addStretch(1)
        self.status_lbl = QLabel("—")
        self.status_lbl.setObjectName("division-status")
        header.addWidget(self.status_lbl)
        self.root_layout.addLayout(header)

        # Category grid
        grid = QGridLayout()
        grid.setSpacing(10)
        for idx, cat in enumerate(self.categories.categories):
            card = self._category_card(cat.key, cat.label)
            grid.addWidget(card, idx // 3, idx % 3)
        self.root_layout.addLayout(grid)

    def _category_card(self, cat_key: str, cat_label: str) -> QWidget:
        w = QWidget()
        w.setObjectName("category-card")
        v = QVBoxLayout(w)
        v.setSpacing(6)
        v.setContentsMargins(12, 12, 12, 12)

        # Title row
        top = QHBoxLayout()
        lbl = QLabel(cat_label)
        lbl.setObjectName("category-title")
        top.addWidget(lbl)
        top.addStretch(1)

        detail_btn = QPushButton("Details")
        detail_btn.setObjectName("detail-btn")
        detail_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        detail_btn.clicked.connect(lambda _c=False, k=cat_key: self._on_detail(k))
        top.addWidget(detail_btn)

        sync_btn = QPushButton("Sync")
        sync_btn.setObjectName("sync-btn")
        sync_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sync_btn.setToolTip("Sync db_ptrj values back to extend_db for this category")
        sync_btn.clicked.connect(lambda _c=False, k=cat_key: self._on_sync(k))
        top.addWidget(sync_btn)

        run_btn = QPushButton("Run")
        run_btn.setObjectName("run-btn")
        run_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        run_btn.clicked.connect(lambda _c=False, k=cat_key: self._on_run(k))
        top.addWidget(run_btn)
        v.addLayout(top)

        # Stats row
        stats = QHBoxLayout()
        stats.setSpacing(16)

        total_lbl = self._stat_box("Total", "0")
        match_lbl = self._stat_box("Match", "0", AppTheme.STATUS_SUCCESS)
        missing_lbl = self._stat_box("Missing", "0", AppTheme.STATUS_ERROR)
        mismatch_lbl = self._stat_box("Mismatch", "0", AppTheme.STATUS_WARNING)
        miss_lbl = self._stat_box("Extra", "0", AppTheme.STATUS_ERROR)

        stats.addWidget(total_lbl["widget"])
        stats.addWidget(match_lbl["widget"])
        stats.addWidget(missing_lbl["widget"])
        stats.addWidget(mismatch_lbl["widget"])
        stats.addWidget(miss_lbl["widget"])
        stats.addStretch(1)
        v.addLayout(stats)

        # Amount row
        amounts = QHBoxLayout()
        missing_amt = QLabel("Missing Amount: 0")
        missing_amt.setStyleSheet("color: #fca5a5; font-size: 12px; font-weight: 700;")
        miss_amt = QLabel("Extra Amount: 0")
        miss_amt.setStyleSheet("color: #fca5a5; font-size: 12px; font-weight: 700;")
        mismatch_amt = QLabel("Mismatch Amount: 0")
        mismatch_amt.setStyleSheet("color: #fcd34d; font-size: 12px; font-weight: 700;")
        amounts.addWidget(missing_amt)
        amounts.addWidget(miss_amt)
        amounts.addWidget(mismatch_amt)
        amounts.addStretch(1)
        v.addLayout(amounts)

        self._category_widgets[cat_key] = {
            "widget": w,
            "detail_btn": detail_btn,
            "sync_btn": sync_btn,
            "run_btn": run_btn,
            "total": total_lbl["value"],
            "match": match_lbl["value"],
            "missing": missing_lbl["value"],
            "mismatch": mismatch_lbl["value"],
            "miss": miss_lbl["value"],
            "missing_amount": missing_amt,
            "miss_amount": miss_amt,
            "mismatch_amount": mismatch_amt,
            "missing_details": [],
            "mismatch_details": [],
            "miss_details": [],
        }
        return w

    def _stat_box(self, label: str, initial: str, color: str | None = None) -> dict[str, Any]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(2)
        v.setContentsMargins(0, 0, 0, 0)
        val = QLabel(initial)
        val.setObjectName("stat-value")
        if color:
            val.setStyleSheet(f"color: {color}; font-weight: 800;")
        lbl = QLabel(label)
        lbl.setObjectName("stat-label")
        v.addWidget(val)
        v.addWidget(lbl)
        return {"widget": w, "value": val}

    def update_category(self, cat_key: str, status: CategoryStatus) -> None:
        widgets = self._category_widgets.get(cat_key)
        if not widgets:
            return
        widgets["total"].setText(str(status.total))
        widgets["match"].setText(str(status.match))
        widgets["missing"].setText(str(status.missing))
        widgets["mismatch"].setText(str(status.mismatch))
        widgets["miss"].setText(str(status.miss))
        widgets["missing_amount"].setText(f"Missing Amount: {status.missing_amount:,.0f}")
        widgets["miss_amount"].setText(f"Extra Amount: {status.miss_amount:,.0f}")
        widgets["mismatch_amount"].setText(f"Mismatch Amount: {status.mismatch_amount:,.0f}")
        widgets["missing_details"] = status.missing_details
        widgets["mismatch_details"] = status.mismatch_details
        widgets["miss_details"] = status.miss_details
        widgets["run_btn"].setEnabled(status.miss > 0)
        widgets["sync_btn"].setEnabled(status.missing > 0 or status.mismatch > 0)
        widgets["detail_btn"].setEnabled(status.missing > 0 or status.mismatch > 0 or status.miss > 0)

    def set_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    def _on_run(self, cat_key: str) -> None:
        cat_label = next((c.label for c in self.categories.categories if c.key == cat_key), cat_key)
        mode = "multi_tab_shared_session"
        widgets = self._category_widgets.get(cat_key, {})
        self.run_requested.emit(self.division_code, cat_key, cat_label, mode, widgets.get("miss_details", []))

    def _on_sync(self, cat_key: str) -> None:
        cat_label = next((c.label for c in self.categories.categories if c.key == cat_key), cat_key)
        self.sync_requested.emit(self.division_code, cat_key, cat_label)

    def _on_detail(self, cat_key: str) -> None:
        widgets = self._category_widgets.get(cat_key)
        if not widgets:
            return
        cat_label = next((c.label for c in self.categories.categories if c.key == cat_key), cat_key)
        details: list[MissDetail] = []
        details.extend(widgets.get("missing_details", []))
        details.extend(widgets.get("mismatch_details", []))
        details.extend(widgets.get("miss_details", []))
        self.detail_requested.emit(self.division_code, cat_label, details)


class DivisionMonitorWidget(QWidget):
    run_division_category = Signal(str, str, str, str, int, int, object)  # division_code, cat_key, cat_label, mode, month, year, extra details

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
        self._sync_threads: dict[str, QThread] = {}
        self._division_cards: dict[str, DivisionCard] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Top controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(8)
        self.mon_month = QSpinBox()
        self.mon_month.setRange(1, 12)
        self.mon_month.setValue(4)
        self.mon_year = QSpinBox()
        self.mon_year.setRange(2000, 2100)
        self.mon_year.setValue(2026)
        form.addRow("Month", self.mon_month)
        form.addRow("Year", self.mon_year)
        ctrl.addLayout(form)

        self.refresh_btn = QPushButton("Refresh All Divisions")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.clicked.connect(self._refresh_all)
        ctrl.addWidget(self.refresh_btn)

        self.only_miss_check = QCheckBox("Show Only Extra")
        self.only_miss_check.setChecked(True)
        self.only_miss_check.stateChanged.connect(self._apply_filter_visibility)
        ctrl.addWidget(self.only_miss_check)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet("color: #f8fafc; font-weight: 700;")
        ctrl.addWidget(self.status_lbl, 1)
        root.addLayout(ctrl)

        # Scrollable division cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(14)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        for division in self.divisions:
            card = DivisionCard(division.code, division.label, self.categories)
            card.run_requested.connect(self._on_card_run)
            card.sync_requested.connect(self._on_card_sync)
            card.detail_requested.connect(self._on_card_detail)
            self._division_cards[division.code] = card
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch(1)
        scroll.setWidget(self.cards_container)
        root.addWidget(scroll, 1)

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
        self.status_lbl.setText(f"Checking {len(codes)} divisions...")
        for card in self._division_cards.values():
            card.set_status("Checking...")
        self.summaries = []
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
        self.status_lbl.setText(f"Checking {code}... ({current}/{total})")
        card = self._division_cards.get(code)
        if card:
            card.set_status(f"Checking... ({current}/{total})")

    def _on_division_done(self, code: str, summary: DivisionSummary) -> None:
        self.summaries.append(summary)
        card = self._division_cards.get(code)
        if card:
            for cat_key, status in summary.categories.items():
                card.update_category(cat_key, status)
            total_extra = sum(s.miss for s in summary.categories.values())
            total_mismatch = sum(s.mismatch for s in summary.categories.values())
            card.set_status(f"Extra: {total_extra} | Mismatch: {total_mismatch}")
        self._apply_filter_visibility()

    def _on_completed(self, summaries: list[DivisionSummary]) -> None:
        self.summaries = summaries
        self.refresh_btn.setEnabled(True)
        total_extra = sum(
            s.categories.get(k, CategoryStatus()).miss
            for s in summaries
            for k in s.categories
        )
        total_mismatch = sum(
            s.categories.get(k, CategoryStatus()).mismatch
            for s in summaries
            for k in s.categories
        )
        self.status_lbl.setText(f"Done. Extra: {total_extra} | Mismatch: {total_mismatch}")
        self._apply_filter_visibility()

    def _on_failed(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_lbl.setText(f"Error: {message}")

    def _apply_filter_visibility(self) -> None:
        show_only_miss = self.only_miss_check.isChecked()
        for code, card in self._division_cards.items():
            summary = next((s for s in self.summaries if s.division_code == code), None)
            if not summary:
                card.setHidden(show_only_miss)
                continue
            total_miss = sum(s.miss for s in summary.categories.values())
            if show_only_miss and total_miss == 0:
                card.setHidden(True)
            else:
                card.setHidden(False)

    def _on_card_run(self, division_code: str, cat_key: str, cat_label: str, mode: str, extra_details: object) -> None:
        self.run_division_category.emit(
            division_code, cat_key, cat_label, mode,
            self.mon_month.value(), self.mon_year.value(), extra_details,
        )

    def _on_card_sync(self, division_code: str, cat_key: str, cat_label: str) -> None:
        filters = filters_for_categories([cat_key]) or None

        card = self._division_cards.get(division_code)
        if card:
            card.set_status(f"Syncing {cat_label}...")

        client = self.api_client_factory()
        thread = QThread(self)
        worker = SyncWorker(
            client, self.mon_month.value(), self.mon_year.value(),
            division_code, filters,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(lambda result, d=division_code, c=cat_label: self._on_sync_completed(d, c, result))
        worker.failed.connect(lambda msg, d=division_code, c=cat_label: self._on_sync_failed(d, c, msg))
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._sync_threads[division_code] = thread
        thread.start()

    def _on_sync_completed(self, division_code: str, cat_label: str, result: dict[str, Any]) -> None:
        data = result.get("data", {})
        synced = data.get("synced_count", 0) if isinstance(data, dict) else 0
        skipped = data.get("skipped_match", 0) if isinstance(data, dict) else 0
        self.status_lbl.setText(f"Sync {division_code}/{cat_label}: {synced} synced, {skipped} skipped")
        card = self._division_cards.get(division_code)
        if card:
            card.set_status(f"Synced {cat_label}: {synced} done")
        QMessageBox.information(
            self, "Sync Complete",
            f"Division: {division_code}\nCategory: {cat_label}\n\n"
            f"Synced: {synced} records\nSkipped: {skipped} (already match)"
        )
        self._sync_threads.pop(division_code, None)
        self._refresh_all()

    def _on_sync_failed(self, division_code: str, cat_label: str, message: str) -> None:
        self.status_lbl.setText(f"Sync {division_code}/{cat_label} failed: {message}")
        card = self._division_cards.get(division_code)
        if card:
            card.set_status(f"Sync {cat_label} failed")
        QMessageBox.critical(self, "Sync Failed", f"{division_code} / {cat_label}\n\n{message}")
        self._sync_threads.pop(division_code, None)

    def _on_card_detail(self, division_code: str, cat_label: str, details: list[MissDetail]) -> None:
        dialog = DetailDialog(division_code, cat_label, details, parent=self)
        dialog.exec()
