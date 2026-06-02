from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
    QScrollArea,
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
from app.core.config import AppConfig, DivisionOption, MAX_CONCURRENT_TABS
from app.core.models import DuplicateDocIdTarget, ManualAdjustmentRecord, RunPayload, enrich_records_with_automation_options, extract_ad_code_from_remarks
from app.core.query_gateway import PlantwareDbPtrjGateway, QueryGatewayConfig
from app.core.run_artifacts import RunArtifactPaths, RunArtifactStore
from app.core.run_service import apply_row_limit, division_mismatch_warning, filter_by_category, filter_records_by_division_prefix
from app.core.runner_bridge import RunnerBridge, RunnerEvent
from app.core.loosefruit_gateway import LoosefruitGatewayRepository
from app.core.task_register_gateway import TaskRegisterGatewayRepository

FetchVerificationStatus = dict[tuple[str, str], dict[str, Any]]
AUTOMATION_OPTION_TYPES = {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH"}
AUTO_BUFFER_CATEGORY_KEYS = {"spsi", "masa_kerja", "tunjangan_jabatan", "pph21"}
SYNC_STATUS_ADJUSTMENT_TYPES = {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "AUTO_BUFFER"}
PREMI_CATEGORY_KEYS = {"premi", "premi_tunjangan", "premi_tiket", "premi_hari_raya", "premi_kehadiran"}
MANUAL_PREVIEW_CATEGORY_KEYS = {"premi", "premi_tunjangan", "potongan_upah_kotor", "potongan_upah_bersih", "koreksi"}
MANUAL_ADJUSTMENT_OPTION_TYPES = "PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH"
DELETE_RUNNER_MODE = "session_reuse_single"
ALL_MISMATCH_FILTERS = ["premi", "potongan", "koreksi", "jabatan", "masa kerja", "spsi", "pph", "potongan upah bersih"]

def sync_status_payload_rows(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", {})
    rows = data.get("rows", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]

def sync_status_rows_by_id(payload: object) -> dict[int, dict[str, Any]]:
    rows_by_id: dict[int, dict[str, Any]] = {}
    for row in sync_status_payload_rows(payload):
        row_id = str(row.get("id") or "").strip()
        if row_id.isdigit():
            rows_by_id[int(row_id)] = row
    return rows_by_id

def compact_sync_amount(value: object) -> str:
    try:
        return f"{float(value or 0):g}"
    except (TypeError, ValueError):
        return "0"

def sync_status_amount_suffix(row: dict[str, Any]) -> str:
    if "adtrans_amount" not in row and "target_amount" not in row:
        return ""
    return f" {compact_sync_amount(row.get('adtrans_amount'))}/{compact_sync_amount(row.get('target_amount'))}"

def sync_status_display_from_row(row: dict[str, Any]) -> tuple[str, str]:
    status = str(row.get("status") or "").upper().strip()
    skip_reason = str(row.get("skip_reason") or "").upper().strip()
    amount_suffix = sync_status_amount_suffix(row)

    if skip_reason == "ADTRANS_AMOUNT_PARTIAL":
        return "PARTIAL", f"{skip_reason}{amount_suffix}"
    if skip_reason == "ADTRANS_NOT_FOUND":
        return "NOT_FOUND", f"{skip_reason}{amount_suffix}"
    if skip_reason == "SYNC_SEGMENT_NOT_FOUND":
        return "NO_SYNC_SEGMENT", skip_reason

    target_units = amount_units(row.get("target_amount", 0))
    adtrans_units = amount_units(row.get("adtrans_amount", 0))
    verified_by_amount = target_units > 0 and adtrans_units >= target_units
    if status in {"UPDATED", "UNCHANGED"} or verified_by_amount:
        return str(row.get("new_sync_status") or "SYNC").upper().strip(), f"{status or 'VERIFIED'}{amount_suffix}".strip()
    if status == "SKIPPED" and skip_reason == "UNCHANGED":
        return str(row.get("new_sync_status") or "SYNC").upper().strip(), f"UNCHANGED{amount_suffix}".strip()
    if status:
        return status, f"{skip_reason or status}{amount_suffix}".strip()
    return "CHECKED", amount_suffix.strip()

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

class EditableTextComboBox(QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:
        self.setCurrentText(value)

    def clear(self) -> None:
        self.setCurrentText("")


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


def record_is_synced(record: ManualAdjustmentRecord) -> bool:
    return sync_status_from_remarks(record).upper() == "SYNC"


def record_is_stale_miss(record: ManualAdjustmentRecord) -> bool:
    sync_status = sync_status_from_remarks(record).upper()
    if sync_status == "SYNC":
        return False
    return sync_status in {"MISS", "MISSING", "NOT_FOUND"}


def filter_for_record(record: ManualAdjustmentRecord) -> str:
    category_key = record.category_key or ""
    if category_key == "masa_kerja":
        return "masa kerja"
    if category_key == "tunjangan_jabatan":
        return "jabatan"
    if category_key == "pph21":
        return "pph"
    if category_key == "potongan_upah_kotor":
        return "potongan"
    if category_key == "potongan_upah_bersih":
        return "potongan upah bersih"
    if category_key == "premi_tunjangan":
        return "premi"
    if category_key == "premi":
        return "premi"
    if category_key == "premi_tiket":
        return "premi"
    if category_key:
        return category_key
    name = record.adjustment_name.strip()
    return (name[5:] if name.upper().startswith("AUTO ") else name).lower()


def records_requiring_fetch_verification(records: list[ManualAdjustmentRecord]) -> list[ManualAdjustmentRecord]:
    return [
        record for record in records
        if not record_is_synced(record) and (record.category_key in PREMI_CATEGORY_KEYS or record_is_stale_miss(record))
    ]

def is_task_desc_adcode(value: str) -> bool:
    return value.strip().upper().startswith(("(AL) ", "(DE) "))


def display_adcode_for_record(record: ManualAdjustmentRecord) -> str:
    for value in (record.ad_code_desc, record.task_desc, record.description, record.ad_code):
        text = (value or "").strip()
        if is_task_desc_adcode(text):
            return text
    return ""


def build_fetch_verification_status(records: list[ManualAdjustmentRecord], data: list[dict[str, Any]]) -> FetchVerificationStatus:
    expected = expected_amounts_by_emp_filter(records)
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


def build_fetch_verification_error(records: list[ManualAdjustmentRecord], error: Exception) -> FetchVerificationStatus:
    return {
        key: {"status": "VERIFY_ERROR", "expected": expected_amount, "actual": 0.0, "message": str(error)}
        for key, expected_amount in expected_amounts_by_emp_filter(records).items()
    }

def expected_amounts_by_emp_filter(records: list[ManualAdjustmentRecord]) -> dict[tuple[str, str], float]:
    expected: dict[tuple[str, str], float] = {}
    for record in records:
        key = (record.emp_code, filter_for_record(record))
        expected[key] = expected.get(key, 0.0) + record.amount
    return expected

def build_premium_retry_plan(
    records: list[ManualAdjustmentRecord],
    verification: FetchVerificationStatus,
) -> tuple[set[str], dict[tuple[str, str], str]]:
    retry_record_keys: set[str] = set()
    held_groups: dict[tuple[str, str], str] = {}
    records_by_filter: dict[tuple[str, str], list[ManualAdjustmentRecord]] = {}
    for record in records:
        if record.category_key not in PREMI_CATEGORY_KEYS:
            continue
        key = (record.emp_code, filter_for_record(record))
        records_by_filter.setdefault(key, []).append(record)

    for key, group_records in records_by_filter.items():
        status_info = verification.get(key, {})
        status = str(status_info.get("status") or "").upper()
        actual_units = amount_units(status_info.get("actual", 0))
        expected_units = amount_units(status_info.get("expected", sum(record.amount for record in group_records)))
        payload_units = sum(amount_units(record.amount) for record in group_records)

        if status == "VERIFIED_NOT_FOUND" or actual_units <= 0:
            retry_record_keys.update(record.record_key for record in group_records)
            continue
        if status == "VERIFIED_MATCH" or actual_units == payload_units or actual_units == expected_units:
            continue
        if status == "VERIFY_ERROR":
            held_groups[key] = "verification error"
            continue
        if status != "VERIFIED_MISMATCH":
            held_groups[key] = "missing verification status"
            continue
        if actual_units > payload_units:
            held_groups[key] = "db amount exceeds payload"
            continue

        entered_indices, hold_reason = unique_subset_indices_for_amount(group_records, actual_units)
        if entered_indices is None:
            held_groups[key] = hold_reason or "ambiguous partial match"
            continue
        for index, record in enumerate(group_records):
            if index not in entered_indices:
                retry_record_keys.add(record.record_key)
    return retry_record_keys, held_groups

def build_premium_retry_plan_from_sync_status(
    records: list[ManualAdjustmentRecord],
    payload: dict[str, Any],
) -> tuple[set[str], dict[tuple[str, str, str], str]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    data = payload.get("data", {})
    rows = data.get("rows", []) if isinstance(data, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or "").strip()
            if row_id:
                rows_by_id[row_id] = row

    records_by_adjustment_id: dict[str, list[ManualAdjustmentRecord]] = {}
    for record in records:
        if record.category_key not in PREMI_CATEGORY_KEYS:
            continue
        adjustment_id = premium_adjustment_row_id(record)
        if not adjustment_id:
            continue
        records_by_adjustment_id.setdefault(adjustment_id, []).append(record)

    retry_record_keys: set[str] = set()
    held_groups: dict[tuple[str, str, str], str] = {}
    for adjustment_id, group_records in records_by_adjustment_id.items():
        row = rows_by_id.get(adjustment_id)
        hold_key = (group_records[0].emp_code, filter_for_record(group_records[0]), adjustment_id)
        if not row:
            held_groups[hold_key] = "missing sync-status row"
            continue

        skip_reason = str(row.get("skip_reason") or "").upper().strip()
        status = str(row.get("status") or "").upper().strip()
        target_units = amount_units(row.get("target_amount", sum(record.amount for record in group_records)))
        adtrans_units = amount_units(row.get("adtrans_amount", 0))
        payload_units = sum(amount_units(record.amount) for record in group_records)
        expected_units = target_units or payload_units

        if skip_reason == "ADTRANS_NOT_FOUND" or adtrans_units <= 0:
            retry_record_keys.update(record.record_key for record in group_records)
            continue
        if skip_reason != "ADTRANS_AMOUNT_PARTIAL" and (
            status in {"UPDATED", "UNCHANGED", "SKIPPED"} or adtrans_units >= expected_units
        ):
            continue
        if skip_reason != "ADTRANS_AMOUNT_PARTIAL":
            held_groups[hold_key] = skip_reason.lower() or status.lower() or "unhandled sync-status row"
            continue

        entered_indices, hold_reason = unique_subset_indices_for_amount(group_records, adtrans_units)
        if entered_indices is None:
            held_groups[hold_key] = hold_reason or "ambiguous partial match"
            continue
        for index, record in enumerate(group_records):
            if index not in entered_indices:
                retry_record_keys.add(record.record_key)
    return retry_record_keys, held_groups

def premium_adjustment_row_id(record: ManualAdjustmentRecord) -> str:
    if record.adjustment_id is not None:
        return str(record.adjustment_id)
    if record.id is not None:
        return str(record.id)
    return ""

def sync_status_ids_for_records(records: list[ManualAdjustmentRecord]) -> list[int]:
    ids: set[int] = set()
    for record in records:
        row_id = premium_adjustment_row_id(record)
        if row_id.isdigit():
            ids.add(int(row_id))
    return sorted(ids)

def verified_sync_status_ids(payload: dict[str, Any]) -> list[int]:
    data = payload.get("data", {})
    rows = data.get("rows", []) if isinstance(data, dict) else []
    verified: set[int] = set()
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id.isdigit():
            continue
        skip_reason = str(row.get("skip_reason") or "").upper().strip()
        if skip_reason in {"ADTRANS_AMOUNT_PARTIAL", "ADTRANS_NOT_FOUND", "SYNC_SEGMENT_NOT_FOUND"}:
            continue
        status = str(row.get("status") or "").upper().strip()
        target_units = amount_units(row.get("target_amount", 0))
        adtrans_units = amount_units(row.get("adtrans_amount", 0))
        if status in {"UPDATED", "UNCHANGED"} or (target_units > 0 and adtrans_units >= target_units):
            verified.add(int(row_id))
    return sorted(verified)

def amount_units(value: object) -> int:
    try:
        return int(round(float(value or 0) * 100))
    except (TypeError, ValueError):
        return 0

def unique_subset_indices_for_amount(
    records: list[ManualAdjustmentRecord],
    target_units: int,
) -> tuple[set[int] | None, str | None]:
    if target_units <= 0:
        return set(), None
    solutions_by_sum: dict[int, list[tuple[int, ...]]] = {0: [()]}
    for index, record in enumerate(records):
        record_units = amount_units(record.amount)
        if record_units <= 0:
            continue
        snapshot = list(solutions_by_sum.items())
        for current_sum, solutions in snapshot:
            next_sum = current_sum + record_units
            if next_sum > target_units:
                continue
            bucket = solutions_by_sum.setdefault(next_sum, [])
            for solution in solutions:
                candidate = solution + (index,)
                if candidate not in bucket:
                    bucket.append(candidate)
                if len(bucket) > 1:
                    bucket[:] = bucket[:2]
                    break

    solutions = solutions_by_sum.get(target_units, [])
    if not solutions:
        return None, "no matching subset"
    if len(solutions) > 1:
        return None, "ambiguous partial match"
    return set(solutions[0]), None

class FetchWorker(QObject):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        query: ManualAdjustmentQuery,
        automation_division_code: str | None = None,
        config: Any = None,
        use_builtin: bool = False,
    ) -> None:
        super().__init__()
        self.client = client
        self.query = query
        self.automation_division_code = automation_division_code
        self.config = config
        self.use_builtin = use_builtin

    def run(self) -> None:
        try:
            fetch_query = self.query.with_grouped_premium_details() if self.query.requests_premium() and not self.query.uses_grouped_view() else self.query
            records = self.client.get_adjustments(fetch_query)
            records = self._enrich_manual_automation_details(records)
            suspect_records = records_requiring_fetch_verification(records)
            verification: FetchVerificationStatus = {}
            if suspect_records:
                premium_records = [record for record in suspect_records if record.category_key in PREMI_CATEGORY_KEYS]
                premium_ids = sorted({
                    int(row_id)
                    for record in premium_records
                    if (row_id := premium_adjustment_row_id(record)).isdigit()
                })
                if premium_records and premium_ids and self.query.division_code:
                    try:
                        sync_payload = self.client.sync_status(
                            period_month=self.query.period_month,
                            period_year=self.query.period_year,
                            division_code=self.query.division_code,
                            gang_code=self.query.gang_code,
                            emp_code=self.query.emp_code,
                            adjustment_type="PREMI",
                            ids=premium_ids,
                            dry_run=True,
                            only_if_adtrans_exists=True,
                            updated_by="browser_automation",
                        )
                        retry_keys, held_groups = build_premium_retry_plan_from_sync_status(premium_records, sync_payload)
                        verification = {
                            "source": "sync-status",
                            "retry_record_keys": retry_keys,
                            "held_groups": held_groups,
                            "sync_status_payload": sync_payload,
                        }
                    except Exception:
                        verification = {}
                if not verification:
                    emp_codes = sorted({record.emp_code for record in suspect_records if record.emp_code})
                    filters = sorted({filter_name for record in suspect_records if (filter_name := filter_for_record(record))})
                    try:
                        if self.use_builtin and self.config:
                            from app.core.built_in_comparison import BuiltInComparisonService
                            from app.core.query_gateway import PlantwareDbPtrjGateway, QueryGatewayConfig

                            gw_config = QueryGatewayConfig(
                                base_url=self.config.query_gateway_base_url,
                                api_key=self.config.query_gateway_api_key,
                                server=self.config.query_gateway_server,
                                database=self.config.query_gateway_database,
                            )
                            query_gateway = PlantwareDbPtrjGateway(
                                config=gw_config,
                                session=self.client.session if hasattr(self.client, 'session') else None
                            )
                            builtin_service = BuiltInComparisonService(
                                config=self.config,
                                query_gateway=query_gateway,
                                api_client=self.client
                            )
                            compare_payload = builtin_service.compare_adtrans(
                                self.query.period_month,
                                self.query.period_year,
                                self.query.division_code,
                                filters=filters if filters else None,
                            )
                            _cd = compare_payload.get("data", {})
                            comparisons = _cd if isinstance(_cd, list) else _cd.get("comparisons", [])
                        elif self.query.division_code:
                            compare_payload = self.client.compare_adtrans(
                                period_month=self.query.period_month,
                                period_year=self.query.period_year,
                                division_code=self.query.division_code,
                                filters=filters,
                            )
                            _cd = compare_payload.get("data", {})
                            comparisons = _cd if isinstance(_cd, list) else _cd.get("comparisons", [])
                        else:
                            comparisons = []

                        if comparisons or (self.use_builtin and self.config):
                            data = []
                            emp_totals = {}
                            for comp in comparisons:
                                emp = str(comp.get("emp_code") or "").upper().strip()
                                cat = str(comp.get("category") or "").lower().strip()
                                actual = float(comp.get("source_amount") or comp.get("db_ptrj_amount") or 0.0)
                                if emp:
                                    emp_totals.setdefault(emp, {})[cat] = actual
                            for emp, totals in emp_totals.items():
                                data.append({"emp_code": emp, **totals})
                        else:
                            data = self.client.check_adtrans(self.query.period_month, self.query.period_year, emp_codes, filters)

                        verification = build_fetch_verification_status(suspect_records, data)
                    except Exception as exc:
                        verification = build_fetch_verification_error(suspect_records, exc)
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
            categories = automation_option_categories_for_records(needs_detail)
            if not categories:
                return records
            options = self.client.get_automation_options(
                division_code=self.automation_division_code or self.query.division_code,
                categories=categories,
                limit=200,
            )
            if not isinstance(options, list):
                return records
            return enrich_records_with_automation_options(records, options)
        except Exception:
            return records


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


class SyncStatusWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        period_month: int,
        period_year: int,
        division_code: str,
        ids: list[int],
        adjustment_type: str | None,
    ) -> None:
        super().__init__()
        self.client = client
        self.period_month = period_month
        self.period_year = period_year
        self.division_code = division_code
        self.ids = ids
        self.adjustment_type = adjustment_type

    def run(self) -> None:
        try:
            dry_run_payload = self.client.sync_status(
                period_month=self.period_month,
                period_year=self.period_year,
                division_code=self.division_code,
                adjustment_type=self.adjustment_type,
                ids=self.ids,
                dry_run=True,
                only_if_adtrans_exists=True,
                updated_by="browser_automation",
            )
            verified_ids = verified_sync_status_ids(dry_run_payload)
            apply_payload: dict[str, Any] | None = None
            if verified_ids:
                apply_payload = self.client.sync_status(
                    period_month=self.period_month,
                    period_year=self.period_year,
                    division_code=self.division_code,
                    adjustment_type=self.adjustment_type,
                    ids=verified_ids,
                    dry_run=False,
                    only_if_adtrans_exists=True,
                    updated_by="browser_automation",
                )
            self.completed.emit({
                "dry_run": dry_run_payload,
                "apply": apply_payload,
                "verified_ids": verified_ids,
            })
        except Exception as exc:
            self.failed.emit(str(exc))

class DuplicateFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        client: ManualAdjustmentApiClient,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str],
        adjustment_type: str | None = None,
        adjustment_name: str | None = None,
        doc_desc: str | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.period_month = period_month
        self.period_year = period_year
        self.division_code = division_code
        self.filters = filters
        self.adjustment_type = adjustment_type
        self.adjustment_name = adjustment_name
        self.doc_desc = doc_desc

    def run(self) -> None:
        try:
            self.completed.emit(self.client.get_duplicate_delete_targets(
                self.period_month,
                self.period_year,
                self.division_code,
                self.filters,
                adjustment_type=self.adjustment_type,
                adjustment_name=self.adjustment_name,
                doc_desc=self.doc_desc,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))


class LoosefruitFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        repository: LoosefruitGatewayRepository,
        loc_code: str | None,
        phy_month: int | None,
        phy_year: int | None,
        limit: int,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.loc_code = loc_code
        self.phy_month = phy_month
        self.phy_year = phy_year
        self.limit = limit

    def run(self) -> None:
        try:
            self.completed.emit(self.repository.list_duplicate_targets(
                loc_code=self.loc_code,
                phy_month=self.phy_month,
                phy_year=self.phy_year,
                limit=self.limit,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))


class TaskRegisterFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        repository: TaskRegisterGatewayRepository,
        loc_code: str | None,
        phy_month: int | None,
        phy_year: int | None,
        limit: int,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.loc_code = loc_code
        self.phy_month = phy_month
        self.phy_year = phy_year
        self.limit = limit

    def run(self) -> None:
        try:
            self.completed.emit(self.repository.list_duplicate_targets(
                loc_code=self.loc_code,
                phy_month=self.phy_month,
                phy_year=self.phy_year,
                limit=self.limit,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))


class ResetDocIdFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, client: ManualAdjustmentApiClient, request: dict[str, Any]) -> None:
        super().__init__()
        self.client = client
        self.request = request

    def run(self) -> None:
        try:
            source_mode = str(self.request.get("source_mode") or "config")
            if source_mode in {"diff", "diff_all"}:
                request = {key: value for key, value in self.request.items() if key != "source_mode"}
                self.completed.emit(self.client.get_mismatch_doc_id_delete_targets(**request))
            else:
                request = {
                    key: value
                    for key, value in self.request.items()
                    if key not in {"source_mode", "gang_code"}
                }
                self.completed.emit(self.client.get_adtrans_doc_id_delete_targets(**request))
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
        self.sync_status_thread: QThread | None = None
        self.sync_status_worker: SyncStatusWorker | None = None
        self.pending_sync_status_ids: set[int] = set()
        self.inflight_sync_status_ids: set[int] = set()
        self.sync_status_unavailable_message = ""
        self.duplicate_fetch_thread: QThread | None = None
        self.duplicate_fetch_worker: DuplicateFetchWorker | None = None
        self.task_register_fetch_thread: QThread | None = None
        self.task_register_fetch_worker: TaskRegisterFetchWorker | None = None
        self.duplicate_targets: list[DuplicateDocIdTarget] = []
        self.duplicate_target_rows: dict[str, int] = {}
        self.reset_docid_fetch_thread: QThread | None = None
        self.reset_docid_fetch_worker: ResetDocIdFetchWorker | None = None
        self.reset_docid_targets: list[DuplicateDocIdTarget] = []
        self.reset_docid_target_rows: dict[str, int] = {}
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
        self.premium_retry_record_keys: set[str] = set()
        self.premium_retry_held_groups: dict[tuple[str, str], str] = {}
        self.last_run_result: dict[str, Any] | None = None
        self.last_successful_records: list[ManualAdjustmentRecord] = []
        self.active_run_payload: RunPayload | None = None
        self.division_run_dialogs: list[QDialog] = []
        self._suppress_adjustment_name_refresh = False
        self.setWindowTitle("Auto Key In Refactor")
        self.resize(1500, 920)
        self.setMinimumSize(900, 600)
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
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

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
        self.tabs.addTab(self._build_reset_docid_tab(), "Reset/Delete DocID")
        self.division_monitor = DivisionMonitorWidget(self._api_client, self.categories, self.divisions, config=self.config)
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
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        api_group = QGroupBox("API Settings")
        api_form = QFormLayout(api_group)
        api_form.setSpacing(8)
        self.api_base_url = QLineEdit(self.config.api_base_url)
        self.api_key = QLineEdit(self.config.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_form.addRow("API Base URL", self.api_base_url)
        api_form.addRow("API Key", self.api_key)

        filter_group = QGroupBox("Data Filter")
        filter_form = QFormLayout(filter_group)
        filter_form.setSpacing(8)
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
        self.adjustment_name = EditableTextComboBox()
        self.adjustment_name.setToolTip("Ketik nama/ADCode/task lalu klik Refresh Adjustment Names untuk filter dari API.")
        self.refresh_adjustment_names_button = QPushButton("Refresh Adjustment Names")
        self.refresh_adjustment_names_button.clicked.connect(self._refresh_adjustment_name_options)
        self.category = QComboBox()
        self.category.addItem("-- (Free / Manual)", "")
        for item in self.categories.categories:
            self.category.addItem(item.label, item.key)
        default_category_index = self.category.findData("premi")
        if default_category_index >= 0:
            self.category.setCurrentIndex(default_category_index)
        self.category.currentIndexChanged.connect(self.apply_category_preset)
        self.adjustment_type.currentIndexChanged.connect(self._refresh_adjustment_name_options)
        self.period_month.valueChanged.connect(self._refresh_adjustment_name_options)
        self.period_year.valueChanged.connect(self._refresh_adjustment_name_options)
        self.gang_code.editingFinished.connect(self._refresh_adjustment_name_options)
        self.emp_code.editingFinished.connect(self._refresh_adjustment_name_options)
        filter_form.addRow("Period Month", self.period_month)
        filter_form.addRow("Period Year", self.period_year)
        filter_form.addRow("Division", self.division_code)
        filter_form.addRow("Gang", self.gang_code)
        filter_form.addRow("Employee", self.emp_code)
        filter_form.addRow("Adjustment Type", self.adjustment_type)
        filter_form.addRow("Adjustment Name", self.adjustment_name)
        filter_form.addRow("", self.refresh_adjustment_names_button)
        filter_form.addRow("Category", self.category)
        self.session_status_label = QLabel("")
        filter_form.addRow("Selected Session", self.session_status_label)
        self.division_code.currentIndexChanged.connect(self._refresh_session_status)
        self.division_code.currentIndexChanged.connect(self._refresh_adjustment_name_options)
        self.division_code.currentIndexChanged.connect(self._sync_task_register_loc_code)

        runner_group = QGroupBox("Runner Settings")
        runner_form = QFormLayout(runner_group)
        runner_form.setSpacing(8)
        self.runner_mode = QComboBox()
        self.runner_mode.addItems(["multi_tab_shared_session", "dry_run", "session_reuse_single", "fresh_login_single", "get_session", "test_session", "mock"])
        self.max_tabs = QSpinBox()
        self.max_tabs.setRange(1, MAX_CONCURRENT_TABS)
        self.max_tabs.setValue(self.config.default_max_tabs)
        self.max_tabs.setToolTip("Only used for multi-tab auto key-in runs. Session checks and single-run modes use one tab.")
        self.row_limit = QSpinBox()
        self.row_limit.setRange(0, 10000)
        self.row_limit.setSpecialValueText("No limit")
        self.row_limit.valueChanged.connect(self._update_process_context)
        self.headless = QCheckBox("Headless")
        self.headless.setChecked(self.config.headless)
        self.only_missing = QCheckBox("Only missing rows")
        self.only_missing.setChecked(True)
        runner_form.addRow("Runner Mode", self.runner_mode)
        runner_form.addRow("Concurrent Tabs (Auto Key-In)", self.max_tabs)
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
        self.session_table.setMaximumHeight(160)
        session_layout.addLayout(session_actions)
        session_layout.addWidget(self.session_table)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(api_group, 0, 0)
        grid.addWidget(filter_group, 1, 0)
        grid.addWidget(runner_group, 0, 1)
        grid.addWidget(session_group, 1, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.apply_preset_button = QPushButton("Apply Preset")
        self.apply_preset_button.setObjectName("primary")
        self.reset_filters_button = QPushButton("Reset")
        self.get_session_button = QPushButton("Get Session")
        self.get_session_button.setObjectName("success")
        self.test_session_button = QPushButton("Test Session")
        self.test_session_button.setObjectName("primary")
        self.add_job_button = QPushButton("Add Job")
        self.add_job_button.setObjectName("success")
        self.apply_preset_button.clicked.connect(self.apply_category_preset)
        self.reset_filters_button.clicked.connect(self.reset_filters)
        self.get_session_button.clicked.connect(self.get_session)
        self.test_session_button.clicked.connect(self.test_session)
        self.add_job_button.clicked.connect(self.add_job_from_current_config)
        actions.addWidget(self.apply_preset_button)
        actions.addWidget(self.reset_filters_button)
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
        
        self.process_only_miss = QCheckBox("Input MISS only")
        self.process_only_miss.setChecked(True)
        self.process_only_miss.setToolTip("Jika aktif, fetch/run hanya memakai MISS. DIFF/MISMATCH harus dihapus dulu dari Reset/Delete DocID.")
        self.process_only_miss.stateChanged.connect(self._update_process_context)
        
        self.process_use_builtin_api = QCheckBox("Cek MISS via Built-in API")
        self.process_use_builtin_api.setChecked(False)
        self.process_use_builtin_api.setToolTip("Gunakan koneksi database langsung untuk mencari data MISS tanpa melewati API Upah.")
        self.process_use_builtin_api.stateChanged.connect(self._update_process_context)

        self.test_get_data_button.clicked.connect(self.fetch_records)
        self.run_button.clicked.connect(self.run_auto_key_in)
        self.run_selected_jobs_button.clicked.connect(self.run_selected_jobs)
        self.stop_button.clicked.connect(self.stop_run)
        self.export_button.clicked.connect(self.open_current_artifacts)
        for button in [self.test_get_data_button, self.run_button, self.run_selected_jobs_button, self.stop_button, self.export_button]:
            controls.addWidget(button)
            
        opt_layout = QVBoxLayout()
        opt_layout.addWidget(self.process_only_miss)
        opt_layout.addWidget(self.process_use_builtin_api)
        controls.addLayout(opt_layout)
        controls.addWidget(self.process_context_label, 1)
        layout.addLayout(controls)

        job_group = QGroupBox("Daftar Job")
        job_layout = QVBoxLayout(job_group)
        self.job_scroll = QScrollArea()
        self.job_scroll.setWidgetResizable(True)
        self.job_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.job_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.job_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.job_table = QTableWidget(0, 10)
        self.job_table.setHorizontalHeaderLabels(["Run", "Division", "Gang", "Category", "Adjustment Type", "Adjustment Name", "Mode", "Max Tabs", "Row Limit", "Status"])
        self.job_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.job_scroll.setWidget(self.job_table)
        job_layout.addWidget(self.job_scroll)
        layout.addWidget(job_group)

        records_scroll = QScrollArea()
        records_scroll.setWidgetResizable(True)
        records_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        records_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        records_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.records_table = QTableWidget(0, 17)
        self.records_table.setHorizontalHeaderLabels(["Input Status", "DB Status", "API Sync", "API Match", "Emp Code", "Gang", "Division", "Adjustment", "Description", "ADCode", "Remarks ADCode", "Amount", "Remarks", "Estate", "DivisionCode", "Detail Type", "Subblok/Vehicle"])
        self.records_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        records_scroll.setWidget(self.records_table)
        layout.addWidget(records_scroll, 3)

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
        self.agent_scroll = QScrollArea()
        self.agent_scroll.setWidgetResizable(True)
        self.agent_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.agent_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.agent_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.agent_scroll.setWidget(self.agent_table)
        layout.addWidget(self.agent_scroll, 1)

        self.run_table = QTableWidget(0, 7)
        self.run_table.setHorizontalHeaderLabels(["Time", "Status", "Emp Code", "Adjustment", "Amount", "Agent/Tab", "Message"])
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.run_scroll = QScrollArea()
        self.run_scroll.setWidgetResizable(True)
        self.run_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.run_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.run_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.run_scroll.setWidget(self.run_table)
        layout.addWidget(self.run_scroll, 2)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(80)
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
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.summary_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.summary_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.summary_scroll.setWidget(self.summary_table)
        layout.addWidget(self.summary_scroll, 1)
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
        self.verify_scroll = QScrollArea()
        self.verify_scroll.setWidgetResizable(True)
        self.verify_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verify_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verify_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.verify_scroll.setWidget(self.verify_table)
        layout.addWidget(self.verify_scroll, 1)
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
        self.duplicate_category = QComboBox()
        for item in self.categories.categories:
            if self._default_filter_for_category_key(item.key):
                self.duplicate_category.addItem(item.label, item.key)
        selected_category_index = self.duplicate_category.findData(str(self.category.currentData() or ""))
        if selected_category_index < 0:
            selected_category_index = self.duplicate_category.findData("spsi")
        if selected_category_index >= 0:
            self.duplicate_category.setCurrentIndex(selected_category_index)
        self.duplicate_filters = QLineEdit(self._default_filter_for_category_key(str(self.duplicate_category.currentData() or "")) or "spsi")
        self.duplicate_category.currentIndexChanged.connect(self._apply_duplicate_category_filter)
        self.duplicate_dry_run = QCheckBox("Dry run: search Plantware, do not delete")
        self.duplicate_dry_run.setChecked(True)
        self.duplicate_dry_run.setToolTip("Browser akan membuka Plantware untuk mencari DocID, tetapi tombol Delete tidak akan diklik.")
        self.fetch_duplicates_button = QPushButton("Fetch Duplicate Targets")
        self.delete_duplicates_button = QPushButton()
        self.delete_duplicates_button.setEnabled(False)
        self.duplicate_status_label = QLabel("Belum dicek.")
        self.fetch_duplicates_button.clicked.connect(self.fetch_duplicate_targets)
        self.delete_duplicates_button.clicked.connect(self.run_duplicate_cleanup)
        self.duplicate_dry_run.toggled.connect(self._sync_duplicate_cleanup_button_text)
        self._sync_duplicate_cleanup_button_text()
        action_row = QHBoxLayout()
        action_row.addWidget(self.fetch_duplicates_button)
        action_row.addWidget(self.delete_duplicates_button)
        action_row.addWidget(self.duplicate_dry_run)
        action_row.addWidget(self.duplicate_status_label, 1)
        form.addRow("Period Month", self.duplicate_month)
        form.addRow("Period Year", self.duplicate_year)
        form.addRow("Division", QLabel("Mengikuti division di tab Config"))
        form.addRow("Category", self.duplicate_category)
        form.addRow("Filters", self.duplicate_filters)
        form.addRow(action_row)

        task_controls = QGroupBox("Task Register duplicate DocID (_01)")
        task_form = QFormLayout(task_controls)
        self.task_register_loc_code = QLineEdit(self._selected_location_code())
        self.task_register_phy_month = QSpinBox()
        self.task_register_phy_month.setRange(0, 12)
        self.task_register_phy_month.setValue(0)
        self.task_register_phy_year = QSpinBox()
        self.task_register_phy_year.setRange(0, 2100)
        self.task_register_phy_year.setValue(0)
        self.task_register_limit = QSpinBox()
        self.task_register_limit.setRange(1, 10000)
        self.task_register_limit.setValue(1000)
        self.fetch_task_register_duplicates_button = QPushButton("Fetch Task Register DocIDs")
        self.delete_task_register_button = QPushButton("Scan Selected (Dry Run)")
        self.delete_task_register_button.setEnabled(False)
        self.task_register_dry_run = QCheckBox("Dry run")
        self.task_register_dry_run.setChecked(True)
        self.task_register_status_label = QLabel("Belum dicek.")
        self.fetch_task_register_duplicates_button.clicked.connect(self.fetch_task_register_duplicate_targets)
        self.delete_task_register_button.clicked.connect(self.run_task_register_delete)
        self.task_register_dry_run.toggled.connect(self._sync_task_register_button_text)
        self._sync_task_register_button_text()
        task_action_row = QHBoxLayout()
        task_action_row.addWidget(self.fetch_task_register_duplicates_button)
        task_action_row.addWidget(self.delete_task_register_button)
        task_action_row.addWidget(self.task_register_dry_run)
        task_action_row.addWidget(self.task_register_status_label, 1)
        task_form.addRow("LocCode", self.task_register_loc_code)
        task_form.addRow("Phy/Actual Month (0=all)", self.task_register_phy_month)
        task_form.addRow("Phy/Actual Year (0=all)", self.task_register_phy_year)
        task_form.addRow("Limit", self.task_register_limit)
        task_form.addRow(task_action_row)

        loosefruit_controls = QGroupBox("Loosefruit duplicate DocID (_)")
        loosefruit_form = QFormLayout(loosefruit_controls)
        self.loosefruit_loc_code = QLineEdit("")
        self.loosefruit_loc_code.setPlaceholderText("Kosong = seluruh lokasi")
        self.loosefruit_limit = QSpinBox()
        self.loosefruit_limit.setRange(1, 10000)
        self.loosefruit_limit.setValue(1000)
        self.loosefruit_tabs = QSpinBox()
        self.loosefruit_tabs.setRange(1, 20)
        self.loosefruit_tabs.setValue(10)
        self.loosefruit_tabs.setToolTip("Jumlah tab paralel untuk delete Loosefruit")
        self.fetch_loosefruit_duplicates_button = QPushButton("Fetch Loosefruit DocIDs")
        self.delete_loosefruit_button = QPushButton("Scan Selected (Dry Run)")
        self.delete_loosefruit_button.setEnabled(False)
        self.loosefruit_dry_run = QCheckBox("Dry run")
        self.loosefruit_dry_run.setChecked(True)
        self.loosefruit_status_label = QLabel("Belum dicek.")
        self.fetch_loosefruit_duplicates_button.clicked.connect(self.fetch_loosefruit_duplicate_targets)
        self.delete_loosefruit_button.clicked.connect(self.run_loosefruit_delete)
        self.loosefruit_dry_run.toggled.connect(self._sync_loosefruit_button_text)
        self._sync_loosefruit_button_text()
        loosefruit_action_row = QHBoxLayout()
        loosefruit_action_row.addWidget(self.fetch_loosefruit_duplicates_button)
        loosefruit_action_row.addWidget(self.delete_loosefruit_button)
        loosefruit_action_row.addWidget(self.loosefruit_dry_run)
        loosefruit_action_row.addWidget(self.loosefruit_status_label, 1)
        loosefruit_form.addRow("LocCode (kosong=all)", self.loosefruit_loc_code)
        loosefruit_form.addRow("Limit", self.loosefruit_limit)
        loosefruit_form.addRow("Parallel Tabs", self.loosefruit_tabs)
        loosefruit_form.addRow(loosefruit_action_row)

        cleanup_grid = QGridLayout()
        cleanup_grid.setHorizontalSpacing(8)
        cleanup_grid.addWidget(controls, 0, 0)
        cleanup_grid.addWidget(task_controls, 0, 1)
        cleanup_grid.addWidget(loosefruit_controls, 1, 0, 1, 2)
        layout.addLayout(cleanup_grid)

        self.duplicate_table = QTableWidget(0, 9)
        self.duplicate_table.setHorizontalHeaderLabels(["Select", "Action", "DocID", "Emp/Loc", "Emp Name", "DocDesc", "Keep DocID", "Status", "Message"])
        self.duplicate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.duplicate_scroll = QScrollArea()
        self.duplicate_scroll.setWidgetResizable(True)
        self.duplicate_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.duplicate_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.duplicate_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.duplicate_scroll.setWidget(self.duplicate_table)
        layout.addWidget(self.duplicate_scroll, 1)
        return tab

    def _build_reset_docid_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QGroupBox("Reset/delete DocID berdasarkan Config aktif")
        form = QFormLayout(controls)
        self.reset_docid_scope_label = QLabel("Mengikuti Period, Division, Employee, Category, Adjustment Type, dan Adjustment Name di tab Config.")
        self.reset_docid_source = QComboBox()
        self.reset_docid_source.addItem("DIFF/MISMATCH DocIDs (dari Config)", "diff")
        self.reset_docid_source.addItem("DIFF/MISMATCH DocIDs – SEMUA Kategori", "diff_all")
        self.reset_docid_dry_run = QCheckBox("Dry run: search Plantware, do not delete")
        self.reset_docid_dry_run.setChecked(True)
        self.reset_docid_dry_run.setToolTip("Browser akan mencari DocID dari compare-adtrans status MISMATCH, tetapi tombol Delete tidak akan diklik.")
        self.fetch_reset_docid_button = QPushButton("Fetch DIFF DocIDs")
        self.run_reset_docid_delete_button = QPushButton()
        self.run_reset_docid_delete_button.setEnabled(False)
        self.reset_docid_status_label = QLabel("Belum dicek.")
        self.fetch_reset_docid_button.clicked.connect(self.fetch_reset_docid_targets)
        self.run_reset_docid_delete_button.clicked.connect(self.run_reset_docid_delete)
        self.reset_docid_dry_run.toggled.connect(self._sync_reset_docid_button_text)
        self._sync_reset_docid_button_text()
        action_row = QHBoxLayout()
        action_row.addWidget(self.fetch_reset_docid_button)
        action_row.addWidget(self.run_reset_docid_delete_button)
        action_row.addWidget(self.reset_docid_dry_run)
        action_row.addWidget(self.reset_docid_status_label, 1)
        form.addRow("Scope", self.reset_docid_scope_label)
        form.addRow("Source", self.reset_docid_source)
        form.addRow(action_row)
        layout.addWidget(controls)

        self.reset_docid_table = QTableWidget(0, 8)
        self.reset_docid_table.setHorizontalHeaderLabels(["Select", "Action", "DocID", "Division", "Category", "Filter", "Status", "Message"])
        self.reset_docid_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.reset_scroll = QScrollArea()
        self.reset_scroll.setWidgetResizable(True)
        self.reset_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.reset_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.reset_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; }")
        self.reset_scroll.setWidget(self.reset_docid_table)
        layout.addWidget(self.reset_scroll, 1)
        return tab

    def reset_filters(self) -> None:
        self.gang_code.clear()
        self.emp_code.clear()
        self.adjustment_type.setCurrentIndex(0)
        self.adjustment_name.setCurrentText("")
        self.only_missing.setChecked(False)
        free_index = self.category.findData("")
        if free_index >= 0:
            self.category.blockSignals(True)
            self.category.setCurrentIndex(free_index)
            self.category.blockSignals(False)
        self._update_process_context()

    def apply_category_preset(self) -> None:
        category_key = str(self.category.currentData() or "")
        self._suppress_adjustment_name_refresh = True
        try:
            if category_key == "spsi":
                self.adjustment_type.setCurrentText("AUTO_BUFFER")
                self._set_adjustment_name_options(["AUTO SPSI"], "AUTO SPSI")
                self.only_missing.setChecked(True)
                self.runner_mode.setCurrentText("multi_tab_shared_session")
            elif category_key == "masa_kerja":
                self.adjustment_type.setCurrentText("AUTO_BUFFER")
                self._set_adjustment_name_options(["MASA KERJA"], "MASA KERJA")
                self.only_missing.setChecked(True)
            elif category_key == "tunjangan_jabatan":
                self.adjustment_type.setCurrentText("AUTO_BUFFER")
                self._set_adjustment_name_options(["TUNJANGAN JABATAN"], "TUNJANGAN JABATAN")
                self.only_missing.setChecked(True)
            elif category_key == "pph21":
                self.adjustment_type.setCurrentText("AUTO_BUFFER")
                self._set_adjustment_name_options(["POTONGAN PPH"], "POTONGAN PPH")
                self.only_missing.setChecked(True)
            elif category_key == "premi_tunjangan":
                self.adjustment_type.setCurrentText("PREMI")
                self.adjustment_name.setCurrentText("TUNJANGAN PREMI")
                self.only_missing.setChecked(False)
                self.process_only_miss.setChecked(True)
            elif category_key in {"premi_tiket", "premi_hari_raya", "premi_kehadiran", "premi"}:
                self.adjustment_type.setCurrentText("PREMI")
                self.adjustment_name.setCurrentText("")
                self.only_missing.setChecked(False)
                self.process_only_miss.setChecked(True)
            elif category_key == "potongan_upah_kotor":
                self.adjustment_type.setCurrentText("POTONGAN_KOTOR")
                self.adjustment_name.setCurrentText("")
                self.only_missing.setChecked(False)
                self.process_only_miss.setChecked(True)
            elif category_key == "potongan_upah_bersih":
                self.adjustment_type.setCurrentText("POTONGAN_BERSIH")
                self.adjustment_name.clear()
                self.only_missing.setChecked(False)
                self.process_only_miss.setChecked(True)
        finally:
            self._suppress_adjustment_name_refresh = False
        self._refresh_adjustment_name_options()
        self._sync_verify_defaults()
        self._update_process_context()

    def _refresh_adjustment_name_options(self) -> None:
        if getattr(self, "_suppress_adjustment_name_refresh", False):
            return
        if not hasattr(self, "adjustment_name"):
            return
        adjustment_type = self._adjustment_name_option_type()
        if not adjustment_type:
            return
        current_text = self.adjustment_name.text().strip()
        search = None
        self._set_adjustment_name_options([], "Loading adjustment names...")
        self.adjustment_name.setEnabled(False)
        self.refresh_adjustment_names_button.setEnabled(False)
        QApplication.processEvents()
        try:
            options = self._api_client().get_adjustment_name_options(
                period_month=self.period_month.value(),
                period_year=self.period_year.value(),
                division_code=self._selected_division_code() or None,
                gang_code=self.gang_code.text().strip().upper() or None,
                emp_code=self.emp_code.text().strip().upper() or None,
                adjustment_type=adjustment_type,
                metadata_only=self._adjustment_name_metadata_only(),
                search=search,
                limit=200,
            )
        except Exception as exc:
            self.append_log(f"Adjustment name options refresh failed: {exc}")
            options = []
        finally:
            self.adjustment_name.setEnabled(True)
            self.refresh_adjustment_names_button.setEnabled(True)
        names = list(dict.fromkeys(option.adjustment_name for option in options if option.adjustment_name))
        self._set_adjustment_name_options(names, current_text)
        self.append_log(f"Loaded {len(names)} adjustment name options for {adjustment_type}.")

    def _adjustment_name_metadata_only(self) -> bool | None:
        category_key = str(self.category.currentData() or "")
        if category_key in PREMI_CATEGORY_KEYS:
            return True
        return None

    def _adjustment_name_option_type(self) -> str | None:
        category_key = str(self.category.currentData() or "")
        if category_key in AUTO_BUFFER_CATEGORY_KEYS:
            return None
        if category_key in PREMI_CATEGORY_KEYS:
            return "PREMI"
        if category_key in {"potongan_upah_kotor", "koreksi"}:
            return "POTONGAN_KOTOR"
        if category_key == "potongan_upah_bersih":
            return "POTONGAN_BERSIH"
        current_type = self.adjustment_type.currentText().strip().upper()
        if current_type == "MANUAL":
            return MANUAL_ADJUSTMENT_OPTION_TYPES
        return current_type or None

    def _set_adjustment_name_options(self, names: list[str], preferred: str = "") -> None:
        was_blocked = self.adjustment_name.blockSignals(True)
        try:
            QComboBox.clear(self.adjustment_name)
            self.adjustment_name.addItems(names)
            self.adjustment_name.setCurrentText(preferred)
        finally:
            self.adjustment_name.blockSignals(was_blocked)

    def add_job_from_current_config(self) -> None:
        job = {
            "period_month": self.period_month.value(),
            "period_year": self.period_year.value(),
            "division_code": self._selected_division_code(),
            "session_division_code": self._selected_session_code(),
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
        runner_mode = str(job.get("runner_mode") or "multi_tab_shared_session")
        division_code = str(job["division_code"]).strip().upper()
        session_division_code = str(job.get("session_division_code") or self._session_code_for_division(division_code)).strip().upper() or division_code
        return RunPayload(
            period_month=int(job["period_month"]),
            period_year=int(job["period_year"]),
            division_code=division_code,
            gang_code=str(job.get("gang_code") or "").strip().upper() or None,
            emp_code=str(job.get("emp_code") or "").strip().upper() or None,
            adjustment_type=str(job.get("adjustment_type") or "").strip().upper() or None,
            adjustment_name=str(job.get("adjustment_name") or "").strip() or None,
            category_key=str(job.get("category_key") or ""),
            runner_mode=runner_mode,
            max_tabs=self._max_tabs_for_mode(runner_mode, int(job.get("max_tabs") or 1)),
            headless=bool(job.get("headless")),
            only_missing_rows=bool(job.get("only_missing_rows")),
            row_limit=job.get("row_limit"),
            records=records,
            session_division_code=session_division_code,
        )

    def run_selected_jobs(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            self.append_log("Tidak ada job yang dipilih.")
            return
        self.append_log(f"Selected jobs ready: {len(jobs)}. Eksekusi queue akan ditambahkan setelah fetch per job.")

    def fetch_records(self) -> None:
        self._prepare_fetch_state()
        current_month = self.period_month.value()
        current_year = self.period_year.value()
        self.append_log(f"Fetching manual adjustment data for {current_month:02d}/{current_year}...")
        client = self._api_client()
        query = ManualAdjustmentQuery(
            period_month=current_month,
            period_year=current_year,
            division_code=self._selected_division_code() or None,
            gang_code=self.gang_code.text().strip() or None,
            emp_code=self.emp_code.text().strip() or None,
            adjustment_type=self.adjustment_type.currentText().strip() or None,
            adjustment_name=self.adjustment_name.text().strip() or None,
        )
        self.fetch_thread = QThread(self)
        self.fetch_worker = FetchWorker(
            client,
            query,
            automation_division_code=self._selected_location_code() or query.division_code,
            config=self.config,
            use_builtin=self.process_use_builtin_api.isChecked(),
        )
        self.fetch_worker.moveToThread(self.fetch_thread)
        self.fetch_thread.started.connect(self.fetch_worker.run)
        self.fetch_worker.completed.connect(self._handle_fetch_completed)
        self.fetch_worker.failed.connect(self._handle_fetch_failed)
        self.fetch_worker.completed.connect(self.fetch_thread.quit)
        self.fetch_worker.failed.connect(self.fetch_thread.quit)
        self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
        self.fetch_thread.start()

    def _prepare_fetch_state(self) -> None:
        self.test_get_data_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.run_selected_jobs_button.setEnabled(False)
        self.records = []
        self.last_successful_records = []
        self.fetch_verification_status = {}
        self.premium_retry_record_keys = set()
        self.premium_retry_held_groups = {}
        self.record_status = {}
        self.records_table.setRowCount(0)
        self.process_context_label.setText("Fetching latest data...")
        self._refresh_summary()

    def _handle_fetch_completed(self, records: list[ManualAdjustmentRecord], verification: FetchVerificationStatus | None = None) -> None:
        self.fetch_verification_status = verification or {}
        if self.fetch_verification_status:
            if self.fetch_verification_status.get("source") == "sync-status":
                sync_payload = self.fetch_verification_status.get("sync_status_payload", {})
                data = sync_payload.get("data", {}) if isinstance(sync_payload, dict) else {}
                self.append_log(
                    "sync-status dry-run: "
                    f"matched={data.get('matched_count', 0)}, "
                    f"adtrans={data.get('adtrans_matched_count', 0)}, "
                    f"updated={data.get('updated_count', 0)}, "
                    f"partial={data.get('partial_count', 0)}, "
                    f"skipped={data.get('skipped_count', 0)}."
                )
            else:
                counts: dict[str, int] = {}
                for item in self.fetch_verification_status.values():
                    if not isinstance(item, dict):
                        continue
                    status = str(item.get("status") or "")
                    counts[status] = counts.get(status, 0) + 1
                self.append_log(f"db_ptrj fetch verification: {len(self.fetch_verification_status)} checked, {counts.get('VERIFIED_MATCH', 0)} match, {counts.get('VERIFIED_MISMATCH', 0)} mismatch, {counts.get('VERIFIED_NOT_FOUND', 0)} not found, {counts.get('VERIFY_ERROR', 0)} error.")
        category_key = str(self.category.currentData() or "")
        row_limit = self.row_limit.value() or None
        filtered_records = filter_by_category(records, category_key)
        filtered_records, division_rejected_records = filter_records_by_division_prefix(filtered_records, self._selected_division_code())
        category_count_after_division_guard = len(filtered_records)
        if division_rejected_records:
            examples = ", ".join(record.emp_code for record in division_rejected_records[:10])
            self.append_log(
                f"Division prefix guard skipped {len(division_rejected_records)} records for {self._selected_division_code()}: "
                f"{examples}. {division_mismatch_warning(division_rejected_records[0], self._selected_division_code())}"
            )
        premium_preview = category_key in PREMI_CATEGORY_KEYS
        self.premium_retry_record_keys = set()
        self.premium_retry_held_groups = {}
        miss_filter_applied = False
        if premium_preview and self.fetch_verification_status:
            if self.fetch_verification_status.get("source") == "sync-status":
                self.premium_retry_record_keys = set(self.fetch_verification_status.get("retry_record_keys", set()))
                self.premium_retry_held_groups = dict(self.fetch_verification_status.get("held_groups", {}))
            else:
                self.premium_retry_record_keys, self.premium_retry_held_groups = build_premium_retry_plan(
                    filtered_records,
                    self.fetch_verification_status,
                )
        if self.process_only_miss.isChecked() and premium_preview and self.fetch_verification_status:
            before_miss_filter = len(filtered_records)
            filtered_records = [record for record in filtered_records if self._record_is_miss(record)]
            miss_filter_applied = True
            self.append_log(
                "Premi retry-safe filter active: "
                f"{len(filtered_records)} verified missing records will be previewed/run; "
                f"{before_miss_filter - len(filtered_records)} matched/mismatch/already-in-db records skipped."
            )
            if self.premium_retry_held_groups:
                self.append_log(
                    "Premi partial hold: "
                    f"{len(self.premium_retry_held_groups)} employee/filter groups need manual check because entered rows could not be identified safely."
                )
        elif self.process_only_miss.isChecked() and premium_preview:
            self.append_log("Premi retry-safe filter skipped: no db_ptrj verification status returned.")
        elif self.process_only_miss.isChecked():
            before_miss_filter = len(filtered_records)
            filtered_records = [record for record in filtered_records if self._record_is_miss(record)]
            miss_filter_applied = True
            self.append_log(f"MISS-only filter active: {len(filtered_records)} of {before_miss_filter} category records will be previewed/run.")
        self.records = apply_row_limit(filtered_records, row_limit)
        self.set_records(self.records)
        filter_suffix = " after MISS-only filter" if miss_filter_applied else ""
        self.append_log(
            f"Fetched {len(records)} raw records; category {category_key or '-'} after division guard has "
            f"{category_count_after_division_guard} records; previewing {len(self.records)} records{filter_suffix}."
        )
        self.test_get_data_button.setEnabled(True)
        self.run_button.setEnabled(bool(self.records))
        self.run_selected_jobs_button.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def _handle_fetch_failed(self, message: str) -> None:
        self.append_log(f"Fetch failed: {message}")
        self.process_context_label.setText("Fetch failed. Check logs.")
        self.test_get_data_button.setEnabled(True)
        self.run_button.setEnabled(bool(self.records))
        self.run_selected_jobs_button.setEnabled(True)

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
        session_jobs: list[tuple[str, str]] = []
        seen_session_codes: set[str] = set()
        configured_codes = {division.code.strip().upper() for division in division_options}
        for division in division_options:
            division_code = division.code.strip().upper()
            if not division_code:
                continue
            session_code = division.effective_session_code
            if session_code in seen_session_codes:
                continue
            seen_session_codes.add(session_code)
            payload_division_code = session_code if session_code in configured_codes else division_code
            session_jobs.append((payload_division_code, session_code))
        self.session_refresh_results = {session_code: "Running" for _, session_code in session_jobs}
        self._set_run_buttons_enabled(False)
        self.stop_button.setEnabled(True)
        self.append_log(f"Starting {len(session_jobs)} browser session logins in parallel...")
        for division_code, session_code in session_jobs:
            payload = self.build_payload(mode="get_session", records=[], division_code=division_code)
            bridge = RunnerBridge(self.config.runner_command)
            thread = QThread(self)
            worker = SessionRefreshWorker(session_code, bridge, payload)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.event_received.connect(self._handle_session_refresh_event)
            worker.completed.connect(self._handle_session_refresh_completed)
            worker.failed.connect(self._handle_session_refresh_failed)
            worker.completed.connect(thread.quit)
            worker.failed.connect(thread.quit)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda code=session_code: self._cleanup_session_refresh_worker(code))
            self.session_refresh_threads[session_code] = thread
            self.session_refresh_workers[session_code] = worker
            self.session_refresh_bridges[session_code] = bridge
            thread.start()
        self.tabs.setCurrentIndex(1)

    def run_session_command(self, mode: str, division_code: str | None = None) -> None:
        target_division = (division_code or self._selected_division_code()).strip().upper()
        payload = self.build_payload(mode=mode, records=[], division_code=target_division)
        session_division = payload.session_division_code or target_division
        suffix = f" via {session_division}" if session_division != target_division else ""
        self.start_runner(payload, f"Starting {mode.replace('_', ' ')} for {target_division}{suffix}...")
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
        _, division_rejected_records = filter_records_by_division_prefix(self.records, self._selected_division_code())
        if division_rejected_records:
            message = (
                f"Run blocked: {len(division_rejected_records)} records do not match selected division "
                f"{self._selected_division_code()}. {division_mismatch_warning(division_rejected_records[0], self._selected_division_code())}"
            )
            self.append_log(message)
            self.process_context_label.setText(message)
            self.tabs.setCurrentIndex(1)
            return
        self._reset_record_status()
        payload = self.build_payload(mode=mode, records=self.records)
        self.start_runner(payload, f"Starting runner for {len(self.records)} records...")
        self.tabs.setCurrentIndex(1)

    def _max_tabs_for_mode(self, mode: str, selected_max_tabs: int | None = None) -> int:
        if mode in {"get_session", "test_session"} or mode.endswith("_single"):
            return 1
        max_tabs = selected_max_tabs if selected_max_tabs is not None else self.max_tabs.value()
        return min(max(1, max_tabs), MAX_CONCURRENT_TABS)

    def build_payload(self, mode: str, records: list[ManualAdjustmentRecord], division_code: str | None = None) -> RunPayload:
        category_key = str(self.category.currentData() or "spsi")
        selected_division_code = (division_code or self._selected_division_code()).strip().upper()
        session_division_code = self._session_code_for_division(selected_division_code) or selected_division_code
        return RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=selected_division_code,
            gang_code=self.gang_code.text().strip().upper() or None,
            emp_code=self.emp_code.text().strip().upper() or None,
            adjustment_type=self.adjustment_type.currentText().strip().upper() or None,
            adjustment_name=self.adjustment_name.text().strip() or None,
            category_key=category_key,
            runner_mode=mode,
            max_tabs=self._max_tabs_for_mode(mode),
            headless=self.headless.isChecked(),
            only_missing_rows=self.only_missing.isChecked(),
            row_limit=self.row_limit.value() or None,
            records=records,
            session_division_code=session_division_code,
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
        self.active_run_payload = payload
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
        if event.event.startswith("task_register."):
            self._handle_duplicate_event(event.event, payload, message)
        if event.event.startswith("loosefruit."):
            self._handle_duplicate_event(event.event, payload, message)
        if event.event.startswith("row.") or event.event.startswith("session.") or event.event.startswith("tab.") or event.event.startswith("task_register.") or event.event.startswith("loosefruit."):
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
        elif event_name == "tab.stopped":
            progress["state"] = "Stopped"
        elif event_name in {"tab.open.failed", "tab.submit.failed", "row.failed"}:
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
        completed_payload = self.active_run_payload
        if self.current_artifacts and isinstance(result, dict):
            self.artifact_store.write_result(self.current_artifacts, result)
            self.last_run_result = result
            self.append_log(f"Result saved: {self.current_artifacts.result_path}")
        self.append_log("Runner completed.")
        if self._payload_is_actual_diff_reset(completed_payload):
            self._apply_post_diff_reset_audit(completed_payload)
        self._set_run_buttons_enabled(True)
        self._refresh_session_status()
        self._refresh_summary()
        if isinstance(result, dict) and int(result.get("inserted_rows") or 0) > 0:
            self._start_sync_status_update_for_successful_records()
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

    def _payload_is_actual_diff_reset(self, payload: RunPayload | None) -> bool:
        if not payload or payload.operation != "delete_duplicates" or payload.delete_dry_run:
            return False
        return any(
            isinstance(target.raw, dict) and target.raw.get("source") == "compare-adtrans"
            for target in payload.duplicate_targets or []
        )

    def _sync_status_scope_for_category(self, category_key: str, payload: RunPayload) -> tuple[str | None, str | None]:
        if category_key == "spsi":
            return "AUTO_BUFFER", "AUTO SPSI"
        if category_key == "masa_kerja":
            return "AUTO_BUFFER", "AUTO MASA KERJA"
        if category_key == "tunjangan_jabatan":
            return "AUTO_BUFFER", "AUTO TUNJANGAN JABATAN"
        if category_key == "pph21":
            return "AUTO_BUFFER", "POTONGAN PPH"
        return payload.adjustment_type, payload.adjustment_name

    def _apply_post_diff_reset_audit(self, payload: RunPayload) -> None:
        adjustment_type, adjustment_name = self._sync_status_scope_for_category(payload.category_key, payload)
        try:
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
        except Exception as exc:
            self.append_log(f"Post-delete sync-status audit failed: {exc}")
            return
        data = result.get("data", {}) if isinstance(result, dict) else {}
        self.append_log(
            "Post-delete sync-status audit applied: "
            f"updated={data.get('updated_count', 0)}, skipped={data.get('skipped_count', 0)}."
        )

    def _start_sync_status_update_for_successful_records(self) -> None:
        records = [
            record for record in self.last_successful_records
            if record.adjustment_type in SYNC_STATUS_ADJUSTMENT_TYPES
        ]
        ids = sync_status_ids_for_records(records)
        if not ids:
            self.append_log("sync-status skipped: no manual adjustment ids found in successful rows.")
            return
        self.append_log(f"sync-status final verification queued for {len(ids)} successful manual adjustment rows.")
        self._queue_sync_status_ids(ids, "QUEUED", "final verification after submit")

    def _sync_status_id_for_record(self, record: ManualAdjustmentRecord) -> int | None:
        if record.adjustment_type not in SYNC_STATUS_ADJUSTMENT_TYPES:
            return None
        row_id = premium_adjustment_row_id(record)
        return int(row_id) if row_id.isdigit() else None

    def _sync_status_adjustment_type_for_ids(self, ids: set[int]) -> str | None:
        adjustment_types = sorted({
            record.adjustment_type
            for record in self.records
            if record.adjustment_type and (row_id := self._sync_status_id_for_record(record)) in ids
        })
        if not adjustment_types:
            selected = self.adjustment_type.currentText().strip().upper()
            return selected if selected in SYNC_STATUS_ADJUSTMENT_TYPES else None
        return adjustment_types[0] if len(adjustment_types) == 1 else ",".join(adjustment_types)

    def _queue_sync_status_for_record(self, record: ManualAdjustmentRecord) -> None:
        if record.adjustment_type not in SYNC_STATUS_ADJUSTMENT_TYPES:
            return
        row_id = self._sync_status_id_for_record(record)
        if row_id is None:
            self._set_record_sync_status(record, "NO_ID", "missing manual adjustment id")
            self._refresh_summary()
            return
        self._queue_sync_status_ids([row_id], "QUEUED", "waiting sync-status verification")

    def _queue_sync_status_ids(self, ids: list[int], status: str, message: str) -> None:
        target_ids = {row_id for row_id in ids if row_id > 0}
        if not target_ids:
            return
        if self.sync_status_unavailable_message:
            self._set_sync_status_for_ids(target_ids, "ERROR", self.sync_status_unavailable_message)
            self._refresh_summary()
            return
        self.pending_sync_status_ids.update(target_ids)
        self._set_sync_status_for_ids(target_ids, status, message)
        self._refresh_summary()
        self._drain_sync_status_queue()

    def _drain_sync_status_queue(self) -> None:
        if self.sync_status_thread is not None or not self.pending_sync_status_ids or self.sync_status_unavailable_message:
            return
        ids = sorted(self.pending_sync_status_ids)
        self.pending_sync_status_ids.clear()
        self.inflight_sync_status_ids = set(ids)
        self._set_sync_status_for_ids(self.inflight_sync_status_ids, "CHECKING", "dry-run/apply sync-status")
        self._refresh_summary()
        adjustment_type = self._sync_status_adjustment_type_for_ids(self.inflight_sync_status_ids)
        self.append_log(f"sync-status dry-run/apply started for {len(ids)} manual adjustment rows.")
        self.sync_status_thread = QThread(self)
        self.sync_status_worker = SyncStatusWorker(
            self._api_client(),
            self.period_month.value(),
            self.period_year.value(),
            self._selected_division_code(),
            ids,
            adjustment_type,
        )
        self.sync_status_worker.moveToThread(self.sync_status_thread)
        self.sync_status_thread.started.connect(self.sync_status_worker.run)
        self.sync_status_worker.completed.connect(self._handle_sync_status_completed)
        self.sync_status_worker.failed.connect(self._handle_sync_status_failed)
        self.sync_status_worker.completed.connect(self.sync_status_thread.quit)
        self.sync_status_worker.failed.connect(self.sync_status_thread.quit)
        self.sync_status_thread.finished.connect(self.sync_status_thread.deleteLater)
        self.sync_status_thread.finished.connect(self._clear_sync_status_thread)
        self.sync_status_thread.start()

    def _handle_sync_status_completed(self, result: object) -> None:
        if not isinstance(result, dict):
            self.append_log("sync-status completed with invalid result shape.")
            return
        dry_run = result.get("dry_run", {})
        apply_payload = result.get("apply")
        verified_ids = result.get("verified_ids", [])
        dry_rows = sync_status_rows_by_id(dry_run)
        apply_rows = sync_status_rows_by_id(apply_payload)
        verified_id_set = {
            int(row_id)
            for row_id in verified_ids
            if isinstance(row_id, int) or str(row_id).isdigit()
        }
        affected_ids = set(self.inflight_sync_status_ids)
        affected_ids.update(dry_rows)
        affected_ids.update(apply_rows)
        affected_ids.update(verified_id_set)
        for row_id in sorted(affected_ids):
            row = apply_rows.get(row_id) or dry_rows.get(row_id)
            if row:
                api_sync, api_match = sync_status_display_from_row(row)
            elif row_id in verified_id_set:
                api_sync, api_match = "SYNC", "VERIFIED"
            else:
                api_sync, api_match = "CHECKED", "no sync-status row"
            self._set_sync_status_for_id(row_id, api_sync, api_match)
        self.inflight_sync_status_ids.clear()
        self._refresh_summary()
        dry_data = dry_run.get("data", {}) if isinstance(dry_run, dict) else {}
        if isinstance(apply_payload, dict):
            apply_data = apply_payload.get("data", {})
            self.append_log(
                "sync-status applied: "
                f"verified_ids={len(verified_ids)}, "
                f"updated={apply_data.get('updated_count', 0)}, "
                f"unchanged={apply_data.get('unchanged_count', 0)}, "
                f"skipped={apply_data.get('skipped_count', 0)}, "
                f"partial={apply_data.get('partial_count', 0)}."
            )
        else:
            self.append_log(
                "sync-status dry-run found no fully verified rows to update: "
                f"matched={dry_data.get('matched_count', 0)}, partial={dry_data.get('partial_count', 0)}, skipped={dry_data.get('skipped_count', 0)}."
            )

    def _handle_sync_status_failed(self, message: str) -> None:
        affected_ids = set(self.inflight_sync_status_ids) | set(self.pending_sync_status_ids)
        self.pending_sync_status_ids.clear()
        self.inflight_sync_status_ids.clear()
        self.sync_status_unavailable_message = message
        if affected_ids:
            self._set_sync_status_for_ids(affected_ids, "ERROR", message)
            self._refresh_summary()
        self.append_log(f"sync-status failed: {message}")

    def _clear_sync_status_thread(self) -> None:
        self.sync_status_thread = None
        self.sync_status_worker = None
        self._drain_sync_status_queue()

    def _set_sync_status_for_ids(self, ids: set[int], api_sync: str, api_match: str) -> None:
        for record in self.records:
            row_id = self._sync_status_id_for_record(record)
            if row_id in ids:
                self._set_record_sync_status(record, api_sync, api_match)

    def _set_sync_status_for_id(self, row_id: int, api_sync: str, api_match: str) -> None:
        self._set_sync_status_for_ids({row_id}, api_sync, api_match)

    def _set_record_sync_status(self, record: ManualAdjustmentRecord, api_sync: str, api_match: str) -> None:
        key = self._record_key(record)
        state = self.record_status.get(key)
        if not state:
            return
        state["api_sync"] = api_sync
        state["api_match"] = api_match
        row = int(state.get("row", -1))
        if row >= 0:
            self.records_table.setItem(row, 2, QTableWidgetItem(api_sync))
            self.records_table.setItem(row, 3, QTableWidgetItem(api_match))

    def set_records(self, records: list[ManualAdjustmentRecord]) -> None:
        self.records = records
        self.records_table.setRowCount(len(records))
        self.record_status = {}
        for row, record in enumerate(records):
            key = self._record_key(record)
            api_sync = self._sync_status_from_remarks(record)
            api_match = self._fetch_verification_display(record) or self._match_status_from_remarks(record)
            db_status = self._db_status_for_record(record)
            self.record_status[key] = {
                "row": row,
                "input_status": "Pending",
                "db_status": db_status,
                "api_sync": api_sync,
                "api_match": api_match,
                "message": "",
            }
            detail_value = record.subblok or record.vehicle_code
            values = ["Pending", db_status, api_sync, api_match, record.emp_code, record.gang_code, record.division_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), self._remarks_adcode(record), f"{record.amount:g}", record.remarks, record.estate, record.divisioncode, record.detail_type, detail_value]
            for column, value in enumerate(values):
                self.records_table.setItem(row, column, QTableWidgetItem(value))
            self._apply_record_row_style(row, "Pending", db_status)
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

    def _reset_docid_request(self) -> dict[str, Any]:
        source_mode = str(self.reset_docid_source.currentData() or "config") if hasattr(self, "reset_docid_source") else "config"
        if source_mode == "diff_all":
            return {
                "period_month": self.period_month.value(),
                "period_year": self.period_year.value(),
                "division_code": self._selected_division_code(),
                "gang_code": self.gang_code.text().strip().upper() or None,
                "emp_code": self.emp_code.text().strip().upper() or None,
                "filters": ALL_MISMATCH_FILTERS,
                "adjustment_type": None,
                "adjustment_name": None,
                "category_key": "",
                "source_mode": "diff_all",
            }
        category_key = str(self.category.currentData() or "")
        default_filter = self._default_filter_for_category_key(category_key)
        filters = [default_filter] if default_filter else []
        adjustment_type = self.adjustment_type.currentText().strip().upper() or None
        adjustment_name = self.adjustment_name.text().strip() or None
        if adjustment_type == "AUTO_BUFFER":
            adjustment_type = None
            adjustment_name = None
        return {
            "period_month": self.period_month.value(),
            "period_year": self.period_year.value(),
            "division_code": self._selected_division_code(),
            "gang_code": self.gang_code.text().strip().upper() or None,
            "emp_code": self.emp_code.text().strip().upper() or None,
            "filters": filters,
            "adjustment_type": adjustment_type,
            "adjustment_name": adjustment_name,
            "category_key": category_key,
            "source_mode": source_mode,
        }

    def fetch_reset_docid_targets(self) -> None:
        request = self._reset_docid_request()
        source_mode = request.get("source_mode", "config")
        if source_mode == "config" and self.gang_code.text().strip() and not self.emp_code.text().strip():
            message = "Reset DocID endpoint belum mendukung filter gang. Kosongkan Gang atau isi Employee untuk scope lebih sempit."
            self.reset_docid_status_label.setText(message)
            self.append_log(message)
            return
        if source_mode not in {"diff", "diff_all"} and not request["filters"] and not request["adjustment_type"] and not request["adjustment_name"]:
            self.reset_docid_status_label.setText("Config filter masih kosong.")
            return
        self.fetch_reset_docid_button.setEnabled(False)
        self.run_reset_docid_delete_button.setEnabled(False)
        source_label = {
            "diff": "compare-adtrans mismatch (config)",
            "diff_all": "compare-adtrans mismatch SEMUA kategori",
        }.get(request.get("source_mode", ""), "db_ptrj config")
        self.reset_docid_status_label.setText(f"Fetching DocID targets from {source_label}...")
        self.reset_docid_fetch_thread = QThread(self)
        self.reset_docid_fetch_worker = ResetDocIdFetchWorker(self._api_client(), request)
        self.reset_docid_fetch_worker.moveToThread(self.reset_docid_fetch_thread)
        self.reset_docid_fetch_thread.started.connect(self.reset_docid_fetch_worker.run)
        self.reset_docid_fetch_worker.completed.connect(self._handle_reset_docid_fetch_completed)
        self.reset_docid_fetch_worker.failed.connect(self._handle_reset_docid_fetch_failed)
        self.reset_docid_fetch_worker.completed.connect(self.reset_docid_fetch_thread.quit)
        self.reset_docid_fetch_worker.failed.connect(self.reset_docid_fetch_thread.quit)
        self.reset_docid_fetch_thread.finished.connect(self.reset_docid_fetch_thread.deleteLater)
        self.reset_docid_fetch_thread.start()

    def _handle_reset_docid_fetch_completed(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.fetch_reset_docid_button.setEnabled(True)
        self.reset_docid_targets = targets
        self._render_reset_docid_targets(targets)
        self.run_reset_docid_delete_button.setEnabled(bool(targets))
        source_label = {
            "diff": "DIFF/MISMATCH (config)",
            "diff_all": "DIFF/MISMATCH SEMUA kategori",
        }.get(str(self.reset_docid_source.currentData() or ""), "config")
        self.reset_docid_status_label.setText(f"Loaded {len(targets)} DELETE_RECORD DocID targets from {source_label}.")

    def _handle_reset_docid_fetch_failed(self, message: str) -> None:
        self.fetch_reset_docid_button.setEnabled(True)
        self.run_reset_docid_delete_button.setEnabled(False)
        self.reset_docid_status_label.setText(f"Fetch failed: {message}")
        self.append_log(f"Reset DocID target fetch failed: {message}")

    def _render_reset_docid_targets(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.reset_docid_target_rows = {}
        self.reset_docid_table.setRowCount(len(targets))
        division_code = self._selected_division_code()
        for row, target in enumerate(targets):
            self.reset_docid_target_rows[target.doc_id] = row
            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Checked if target.action == "DELETE_RECORD" else Qt.CheckState.Unchecked)
            self.reset_docid_table.setItem(row, 0, select_item)
            values = [target.action, target.doc_id, division_code, target.category, target.doc_desc, "Pending", ""]
            for column, value in enumerate(values, start=1):
                self.reset_docid_table.setItem(row, column, QTableWidgetItem(str(value)))

    def run_reset_docid_delete(self) -> None:
        if self._runner_is_active():
            self.reset_docid_status_label.setText("Runner sedang berjalan.")
            return
        selected = self._selected_reset_docid_targets()
        if not selected:
            self.reset_docid_status_label.setText("Tidak ada DocID target yang dipilih.")
            return
        if not self._selected_session_active():
            division_code = self._selected_division_code()
            message = f"Session aktif untuk {division_code} belum ada. Jalankan Get Session dulu sebelum reset/delete DIFF."
            self.reset_docid_status_label.setText(message)
            self.append_log(f"Reset DocID delete blocked: {message}")
            QMessageBox.warning(self, "Session belum aktif", message)
            self.tabs.setCurrentIndex(0)
            return
        if not self.reset_docid_dry_run.isChecked():
            answer = QMessageBox.question(self, "Confirm Reset/Delete DocID", f"Delete {len(selected)} DIFF/MISMATCH DocIDs from {self._selected_division_code()}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.reset_docid_status_label.setText("Actual delete dibatalkan.")
                return
        dry_run = self.reset_docid_dry_run.isChecked()
        action_label = "dry-run scan" if dry_run else "delete"
        self.reset_docid_status_label.setText(f"Starting reset {action_label} for {len(selected)} DocIDs...")
        self.append_log(f"Reset DocID selected targets: {[target.doc_id for target in selected[:20]]}; dry_run={dry_run}")
        base_payload = self.build_payload(mode=DELETE_RUNNER_MODE, records=[])
        payload = RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=self._selected_division_code(),
            gang_code=base_payload.gang_code,
            emp_code=base_payload.emp_code,
            adjustment_type=base_payload.adjustment_type,
            adjustment_name=base_payload.adjustment_name,
            category_key=str(self.category.currentData() or base_payload.category_key),
            runner_mode=DELETE_RUNNER_MODE,
            max_tabs=base_payload.max_tabs,
            headless=base_payload.headless,
            only_missing_rows=base_payload.only_missing_rows,
            row_limit=base_payload.row_limit,
            records=[],
            session_division_code=base_payload.session_division_code,
            operation="delete_duplicates",
            duplicate_targets=selected,
            delete_dry_run=dry_run,
        )
        self.start_runner(payload, f"Starting reset {action_label} for {len(selected)} DocIDs...")
        self.tabs.setCurrentIndex(1)

    def _selected_reset_docid_targets(self) -> list[DuplicateDocIdTarget]:
        selected: list[DuplicateDocIdTarget] = []
        for row, target in enumerate(self.reset_docid_targets):
            item = self.reset_docid_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked and target.action == "DELETE_RECORD":
                selected.append(target)
        return selected

    def fetch_loosefruit_duplicate_targets(self) -> None:
        loc_code = self.loosefruit_loc_code.text().strip().upper() or None
        self.fetch_loosefruit_duplicates_button.setEnabled(False)
        self.delete_loosefruit_button.setEnabled(False)
        self.delete_duplicates_button.setEnabled(False)
        self.loosefruit_status_label.setText("Fetching Loosefruit DocIDs via Query Gateway...")
        self.duplicate_status_label.setText("Fetching Loosefruit DocIDs via Query Gateway...")
        repository = self._loosefruit_repository()
        self.loosefruit_fetch_thread = QThread(self)
        self.loosefruit_fetch_worker = LoosefruitFetchWorker(
            repository,
            loc_code=loc_code,
            phy_month=None,
            phy_year=None,
            limit=self.loosefruit_limit.value(),
        )
        self.loosefruit_fetch_worker.moveToThread(self.loosefruit_fetch_thread)
        self.loosefruit_fetch_thread.started.connect(self.loosefruit_fetch_worker.run)
        self.loosefruit_fetch_worker.completed.connect(self._handle_loosefruit_fetch_completed)
        self.loosefruit_fetch_worker.failed.connect(self._handle_loosefruit_fetch_failed)
        self.loosefruit_fetch_worker.completed.connect(self.loosefruit_fetch_thread.quit)
        self.loosefruit_fetch_worker.failed.connect(self.loosefruit_fetch_thread.quit)
        self.loosefruit_fetch_thread.finished.connect(self.loosefruit_fetch_thread.deleteLater)
        self.loosefruit_fetch_thread.start()

    def _handle_loosefruit_fetch_completed(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.fetch_loosefruit_duplicates_button.setEnabled(True)
        self.duplicate_targets = targets
        self._render_duplicate_targets(targets)
        enabled = bool(targets)
        self.delete_duplicates_button.setEnabled(enabled)
        self.delete_loosefruit_button.setEnabled(enabled)
        loc_codes = self._duplicate_target_loc_codes(targets)
        loc_text = "all locations" if not self.loosefruit_loc_code.text().strip() else ", ".join(loc_codes)
        message = f"Loaded {len(targets)} Loosefruit DocID targets for {loc_text}."
        if not self.loosefruit_loc_code.text().strip() and loc_codes:
            message = f"Loaded {len(targets)} Loosefruit DocID targets across {len(loc_codes)} LocCode(s)."
        self.loosefruit_status_label.setText(message)
        self.duplicate_status_label.setText(message)

    def _handle_loosefruit_fetch_failed(self, message: str) -> None:
        self.fetch_loosefruit_duplicates_button.setEnabled(True)
        self.delete_loosefruit_button.setEnabled(False)
        self.loosefruit_status_label.setText(f"Fetch failed: {message}")
        self.duplicate_status_label.setText(f"Fetch failed: {message}")
        self.append_log(f"Loosefruit target fetch failed: {message}")

    def run_loosefruit_delete(self) -> None:
        selected = self._selected_duplicate_targets()
        if not selected:
            self.loosefruit_status_label.setText("Pilih DocID yang akan dihapus dari table.")
            return
        dry_run = self.loosefruit_dry_run.isChecked()
        loc_codes = self._duplicate_target_loc_codes(selected)
        if not loc_codes:
            fallback = self.loosefruit_loc_code.text().strip().upper() or self._selected_location_code()
            if fallback:
                loc_codes = [fallback]
        for loc_code in (loc_codes or [""]):
            if loc_code and not self._session_active_for_code(loc_code):
                message = f"Session aktif untuk {loc_code} belum ada. Jalankan Get Session dulu."
                self.loosefruit_status_label.setText(message)
                QMessageBox.warning(self, "Session belum aktif", message)
                self.tabs.setCurrentIndex(0)
                return
        if not dry_run:
            loc_text = ", ".join(loc_codes) if loc_codes else "unknown"
            answer = QMessageBox.question(
                self, "Confirm Delete",
                f"Yakin hapus {len(selected)} Loosefruit DocIDs di {len(loc_codes)} LocCode ({loc_text})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.loosefruit_status_label.setText("Delete dibatalkan.")
                return
        action_label = "dry-run" if dry_run else "delete"
        self.loosefruit_status_label.setText(f"Starting Loosefruit {action_label} for {len(selected)} DocIDs...")
        self.duplicate_status_label.setText(f"Starting Loosefruit {action_label} for {len(selected)} DocIDs...")
        first_loc = loc_codes[0] if loc_codes else self._selected_location_code()
        payload = RunPayload(
            period_month=self.period_month.value(),
            period_year=self.period_year.value(),
            division_code=first_loc,
            gang_code=None,
            emp_code=None,
            adjustment_type=None,
            adjustment_name=None,
            category_key="loosefruit",
            runner_mode="delete_loosefruit",
            max_tabs=max(1, self.loosefruit_tabs.value()),
            headless=False,
            only_missing_rows=False,
            row_limit=None,
            records=[],
            session_division_code=first_loc,
            operation="delete_loosefruit",
            duplicate_targets=selected,
            delete_dry_run=dry_run,
        )
        self.start_runner(payload, f"Loosefruit {action_label}: {len(selected)} DocIDs...")

    def fetch_task_register_duplicate_targets(self) -> None:
        loc_code = self.task_register_loc_code.text().strip().upper() or self._selected_location_code()
        if not loc_code:
            self.task_register_status_label.setText("LocCode masih kosong.")
            return
        self.fetch_task_register_duplicates_button.setEnabled(False)
        self.delete_duplicates_button.setEnabled(False)
        self.task_register_status_label.setText("Fetching Task Register DocIDs via Query Gateway...")
        self.duplicate_status_label.setText("Fetching Task Register DocIDs via Query Gateway...")
        repository = self._task_register_repository()
        self.task_register_fetch_thread = QThread(self)
        self.task_register_fetch_worker = TaskRegisterFetchWorker(
            repository,
            loc_code=loc_code,
            phy_month=self.task_register_phy_month.value() or None,
            phy_year=self.task_register_phy_year.value() or None,
            limit=self.task_register_limit.value(),
        )
        self.task_register_fetch_worker.moveToThread(self.task_register_fetch_thread)
        self.task_register_fetch_thread.started.connect(self.task_register_fetch_worker.run)
        self.task_register_fetch_worker.completed.connect(self._handle_task_register_fetch_completed)
        self.task_register_fetch_worker.failed.connect(self._handle_task_register_fetch_failed)
        self.task_register_fetch_worker.completed.connect(self.task_register_fetch_thread.quit)
        self.task_register_fetch_worker.failed.connect(self.task_register_fetch_thread.quit)
        self.task_register_fetch_thread.finished.connect(self.task_register_fetch_thread.deleteLater)
        self.task_register_fetch_thread.start()

    def _handle_task_register_fetch_completed(self, targets: list[DuplicateDocIdTarget]) -> None:
        self.fetch_task_register_duplicates_button.setEnabled(True)
        self.duplicate_targets = targets
        self._render_duplicate_targets(targets)
        self.delete_duplicates_button.setEnabled(bool(targets))
        self.delete_task_register_button.setEnabled(bool(targets))
        loc_code = self.task_register_loc_code.text().strip().upper() or self._selected_location_code()
        message = f"Loaded {len(targets)} Task Register DocID targets for {loc_code}."
        self.task_register_status_label.setText(message)
        self.duplicate_status_label.setText(message)

    def _handle_task_register_fetch_failed(self, message: str) -> None:
        self.fetch_task_register_duplicates_button.setEnabled(True)
        self.delete_task_register_button.setEnabled(False)
        self.task_register_status_label.setText(f"Fetch failed: {message}")
        self.duplicate_status_label.setText(f"Fetch failed: {message}")
        self.append_log(f"Task Register target fetch failed: {message}")

    def run_task_register_delete(self) -> None:
        selected = self._selected_duplicate_targets()
        if not selected:
            self.task_register_status_label.setText("Pilih DocID yang akan dihapus dari table.")
            return
        dry_run = self.task_register_dry_run.isChecked()
        loc_code = self.task_register_loc_code.text().strip().upper() or self._selected_location_code()
        if not self._session_active_for_code(loc_code):
            message = f"Session aktif untuk {loc_code} belum ada. Jalankan Get Session dulu."
            self.task_register_status_label.setText(message)
            QMessageBox.warning(self, "Session belum aktif", message)
            self.tabs.setCurrentIndex(0)
            return
        if not dry_run:
            answer = QMessageBox.question(
                self, "Confirm Delete",
                f"Yakin hapus {len(selected)} Task Register DocIDs?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.task_register_status_label.setText("Delete dibatalkan.")
                return
        action_label = "dry-run" if dry_run else "delete"
        self.task_register_status_label.setText(f"Starting Task Register {action_label} for {len(selected)} DocIDs...")
        self.duplicate_status_label.setText(f"Starting Task Register {action_label} for {len(selected)} DocIDs...")
        payload = RunPayload(
            period_month=5,
            period_year=2026,
            division_code=loc_code,
            gang_code=None,
            emp_code=None,
            adjustment_type=None,
            adjustment_name=None,
            category_key="task_register",
            runner_mode="delete_duplicates",
            max_tabs=1,
            headless=False,
            only_missing_rows=False,
            row_limit=None,
            records=[],
            session_division_code=loc_code,
            operation="delete_duplicates",
            duplicate_targets=selected,
            delete_dry_run=dry_run,
        )
        self.start_runner(payload, f"Task Register {action_label}: {len(selected)} DocIDs...")

    def fetch_duplicate_targets(self) -> None:
        if not self._duplicate_category_supported():
            self.duplicate_status_label.setText("Pilih kategori duplicate cleanup yang valid.")
            return
        request = self._duplicate_cleanup_request()
        if not request["filters"] and not request["adjustment_type"] and not request["adjustment_name"] and not request["doc_desc"]:
            self.duplicate_status_label.setText("Filters atau adjustment config masih kosong.")
            return
        self.fetch_duplicates_button.setEnabled(False)
        self.delete_duplicates_button.setEnabled(False)
        self.duplicate_status_label.setText("Fetching duplicate targets...")
        self.duplicate_fetch_thread = QThread(self)
        self.duplicate_fetch_worker = DuplicateFetchWorker(self._api_client(), **request)
        self.duplicate_fetch_worker.moveToThread(self.duplicate_fetch_thread)
        self.duplicate_fetch_thread.started.connect(self.duplicate_fetch_worker.run)
        self.duplicate_fetch_worker.completed.connect(self._handle_duplicate_fetch_completed)
        self.duplicate_fetch_worker.failed.connect(self._handle_duplicate_fetch_failed)
        self.duplicate_fetch_worker.completed.connect(self.duplicate_fetch_thread.quit)
        self.duplicate_fetch_worker.failed.connect(self.duplicate_fetch_thread.quit)
        self.duplicate_fetch_thread.finished.connect(self.duplicate_fetch_thread.deleteLater)
        self.duplicate_fetch_thread.start()

    def _duplicate_cleanup_request(self) -> dict[str, Any]:
        category_key = str(self.duplicate_category.currentData() or "")
        filters = self._parse_list(self.duplicate_filters.text())
        adjustment_type: str | None = None
        adjustment_name: str | None = None
        doc_desc: str | None = None
        config_category_key = str(self.category.currentData() or "")
        config_adjustment_type = self.adjustment_type.currentText().strip().upper()
        config_adjustment_name = self.adjustment_name.text().strip()
        if (
            category_key == config_category_key
            and config_adjustment_type in SYNC_STATUS_ADJUSTMENT_TYPES
        ):
            adjustment_type = config_adjustment_type
            adjustment_name = config_adjustment_name or None
            filters = []
        return {
            "period_month": self.duplicate_month.value(),
            "period_year": self.duplicate_year.value(),
            "division_code": self._selected_division_code(),
            "filters": filters,
            "adjustment_type": adjustment_type,
            "adjustment_name": adjustment_name,
            "doc_desc": doc_desc,
        }

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
            select_item.setCheckState(Qt.CheckState.Checked if target.action in {"DELETE_OLD", "DELETE_RECORD"} else Qt.CheckState.Unchecked)
            self.duplicate_table.setItem(row, 0, select_item)
            loc_code = self._duplicate_target_loc_code(target)
            values = [target.action, target.doc_id, target.emp_code or loc_code, target.emp_name, target.doc_desc, target.keep_doc_id, "Pending", ""]
            for column, value in enumerate(values, start=1):
                self.duplicate_table.setItem(row, column, QTableWidgetItem(str(value)))

    def run_duplicate_cleanup(self) -> None:
        if self._runner_is_active():
            self.duplicate_status_label.setText("Runner sedang berjalan.")
            return
        selected = self._selected_duplicate_targets()
        if not selected:
            self.duplicate_status_label.setText("Tidak ada duplicate target yang dipilih.")
            return
        task_register_targets = self._targets_are_task_register(selected)
        if not task_register_targets and not self._duplicate_category_supported():
            self.duplicate_status_label.setText("Pilih kategori duplicate cleanup yang valid.")
            return
        try:
            runner_division_code = self._duplicate_run_division_code(selected)
        except ValueError as exc:
            self.duplicate_status_label.setText(str(exc))
            return
        if not self._session_active_for_code(runner_division_code):
            message = f"Session aktif untuk {runner_division_code} belum ada. Jalankan Get Session dulu sebelum delete duplicate."
            self.duplicate_status_label.setText(message)
            self.append_log(f"Duplicate cleanup blocked: {message}")
            QMessageBox.warning(self, "Session belum aktif", message)
            self.tabs.setCurrentIndex(0)
            return
        if not self.duplicate_dry_run.isChecked():
            answer = QMessageBox.question(self, "Confirm Duplicate Delete", f"Delete {len(selected)} duplicate DocIDs from {runner_division_code}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.duplicate_status_label.setText("Actual delete dibatalkan.")
                return
        dry_run = self.duplicate_dry_run.isChecked()
        action_label = "dry-run scan" if dry_run else "delete"
        self.duplicate_status_label.setText(f"Starting duplicate {action_label} for {len(selected)} DocIDs...")
        self.append_log(f"Duplicate cleanup selected targets: {[(target.doc_id, target.master_id) for target in selected[:10]]}; dry_run={dry_run}")
        payload = self.build_payload(mode=DELETE_RUNNER_MODE, records=[], division_code=runner_division_code)
        duplicate_category_key = "task_register" if task_register_targets else str(self.duplicate_category.currentData() or payload.category_key)
        period_month, period_year = self._duplicate_run_period(selected, default_month=self.duplicate_month.value(), default_year=self.duplicate_year.value())
        payload = RunPayload(
            period_month=period_month,
            period_year=period_year,
            division_code=runner_division_code,
            gang_code=payload.gang_code,
            emp_code=payload.emp_code,
            adjustment_type=payload.adjustment_type,
            adjustment_name=payload.adjustment_name,
            category_key=duplicate_category_key,
            runner_mode=DELETE_RUNNER_MODE,
            max_tabs=payload.max_tabs,
            headless=payload.headless,
            only_missing_rows=payload.only_missing_rows,
            row_limit=payload.row_limit,
            records=[],
            session_division_code=payload.session_division_code,
            operation="delete_duplicates",
            duplicate_targets=selected,
            delete_dry_run=dry_run,
        )
        self.start_runner(payload, f"Starting duplicate {action_label} for {len(selected)} DocIDs...")
        self.tabs.setCurrentIndex(1)

    def _selected_duplicate_targets(self) -> list[DuplicateDocIdTarget]:
        selected: list[DuplicateDocIdTarget] = []
        for row, target in enumerate(self.duplicate_targets):
            item = self.duplicate_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked and target.action in {"DELETE_OLD", "DELETE_RECORD"}:
                selected.append(target)
        return selected

    def _targets_are_task_register(self, targets: list[DuplicateDocIdTarget]) -> bool:
        if not targets:
            return False
        return all(
            target.category == "task_register"
            or str((target.raw or {}).get("source") or "") == "task-register-pr-taskreg"
            for target in targets
        )

    def _targets_are_loosefruit(self, targets: list[DuplicateDocIdTarget]) -> bool:
        if not targets:
            return False
        return all(
            target.category == "loosefruit"
            or str((target.raw or {}).get("source") or "") == "loosefruit-pr-loosefruit"
            for target in targets
        )

    def _duplicate_target_loc_code(self, target: DuplicateDocIdTarget) -> str:
        raw = target.raw or {}
        return str(raw.get("loc_code") or raw.get("locCode") or raw.get("LocCode") or "").strip().upper()

    def _duplicate_target_loc_codes(self, targets: list[DuplicateDocIdTarget]) -> list[str]:
        return sorted({loc for target in targets if (loc := self._duplicate_target_loc_code(target))})

    def _duplicate_run_division_code(self, targets: list[DuplicateDocIdTarget]) -> str:
        if not self._targets_are_task_register(targets):
            return self._selected_division_code()
        loc_codes = sorted({loc_code for target in targets if (loc_code := self._duplicate_target_loc_code(target))})
        if len(loc_codes) > 1:
            raise ValueError(f"Task Register delete hanya boleh satu LocCode per run: {', '.join(loc_codes)}")
        return loc_codes[0] if loc_codes else (self.task_register_loc_code.text().strip().upper() or self._selected_location_code())

    def _duplicate_run_period(self, targets: list[DuplicateDocIdTarget], default_month: int, default_year: int) -> tuple[int, int]:
        if not self._targets_are_task_register(targets):
            return default_month, default_year
        raw = targets[0].raw or {}
        try:
            month = int(raw.get("acc_month") or raw.get("accMonth") or default_month)
        except (TypeError, ValueError):
            month = default_month
        try:
            year = int(raw.get("acc_year") or raw.get("accYear") or default_year)
        except (TypeError, ValueError):
            year = default_year
        return month, year

    def _handle_duplicate_event(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        doc_id = str(payload.get("doc_id", ""))
        row = self.duplicate_target_rows.get(doc_id)
        if row is not None:
            status = str(payload.get("status") or event_name.rsplit(".", 1)[-1])
            self.duplicate_table.setItem(row, 7, QTableWidgetItem(status))
            self.duplicate_table.setItem(row, 8, QTableWidgetItem(message))
        reset_row = self.reset_docid_target_rows.get(doc_id)
        if reset_row is not None:
            status = str(payload.get("status") or event_name.rsplit(".", 1)[-1])
            self.reset_docid_table.setItem(reset_row, 6, QTableWidgetItem(status))
            self.reset_docid_table.setItem(reset_row, 7, QTableWidgetItem(message))
        counts = {"deleted": 0, "dry_run": 0, "not_found": 0, "failed": 0}
        for row_index in range(self.duplicate_table.rowCount()):
            status_item = self.duplicate_table.item(row_index, 7)
            status = status_item.text() if status_item else ""
            if status in counts:
                counts[status] += 1
        self.duplicate_status_label.setText(f"Deleted: {counts['deleted']} | Dry-run: {counts['dry_run']} | Not found: {counts['not_found']} | Failed: {counts['failed']}")
        reset_counts = {"deleted": 0, "dry_run": 0, "not_found": 0, "failed": 0}
        for row_index in range(self.reset_docid_table.rowCount()):
            status_item = self.reset_docid_table.item(row_index, 6)
            status = status_item.text() if status_item else ""
            if status in reset_counts:
                reset_counts[status] += 1
        if reset_row is not None:
            self.reset_docid_status_label.setText(f"Deleted: {reset_counts['deleted']} | Dry-run: {reset_counts['dry_run']} | Not found: {reset_counts['not_found']} | Failed: {reset_counts['failed']}")
        self._append_event_row(event_name, payload, message)

    def _duplicate_category_supported(self) -> bool:
        if not hasattr(self, "duplicate_category"):
            return False
        if self.duplicate_targets and self._targets_are_task_register(self.duplicate_targets):
            return True
        return bool(self._default_filter_for_category_key(str(self.duplicate_category.currentData() or "")))

    def _apply_duplicate_category_filter(self) -> None:
        if not hasattr(self, "duplicate_filters"):
            return
        default_filter = self._default_filter_for_category_key(str(self.duplicate_category.currentData() or ""))
        if default_filter:
            self.duplicate_filters.setText(default_filter)

    def _sync_duplicate_cleanup_button_text(self) -> None:
        if not hasattr(self, "delete_duplicates_button") or not hasattr(self, "duplicate_dry_run"):
            return
        if self.duplicate_dry_run.isChecked():
            self.delete_duplicates_button.setText("Scan Selected Duplicates (Dry Run)")
        else:
            self.delete_duplicates_button.setText("Delete Selected Duplicates")

    def _sync_task_register_button_text(self) -> None:
        if not hasattr(self, "delete_task_register_button") or not hasattr(self, "task_register_dry_run"):
            return
        if self.task_register_dry_run.isChecked():
            self.delete_task_register_button.setText("Scan Selected (Dry Run)")
        else:
            self.delete_task_register_button.setText("Delete Selected")

    def _sync_loosefruit_button_text(self) -> None:
        if not hasattr(self, "delete_loosefruit_button") or not hasattr(self, "loosefruit_dry_run"):
            return
        if self.loosefruit_dry_run.isChecked():
            self.delete_loosefruit_button.setText("Scan Selected (Dry Run)")
        else:
            self.delete_loosefruit_button.setText("Delete Selected")

    def _sync_reset_docid_button_text(self) -> None:
        if not hasattr(self, "run_reset_docid_delete_button") or not hasattr(self, "reset_docid_dry_run"):
            return
        if self.reset_docid_dry_run.isChecked():
            self.run_reset_docid_delete_button.setText("Scan Selected DocIDs (Dry Run)")
        else:
            self.run_reset_docid_delete_button.setText("Delete Selected DocIDs")

    def _update_record_from_event(self, event_name: str, payload: dict[str, Any], message: str) -> None:
        record = self._find_record(str(payload.get("emp_code", "")), str(payload.get("adjustment_name", "")), str(payload.get("detail_key", "") or ""))
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
        if event_name == "row.success":
            self._queue_sync_status_for_record(record)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        success_records: list[ManualAdjustmentRecord] = []
        failed_records: list[ManualAdjustmentRecord] = []
        table_rows: list[list[str]] = []
        for record in self.records:
            state = self.record_status.get(self._record_key(record), {})
            input_status = str(state.get("input_status", "Pending"))
            db_status = str(state.get("db_status", "Not Checked"))
            api_sync = str(state.get("api_sync", self._sync_status_from_remarks(record)))
            api_match = str(state.get("api_match", self._match_status_from_remarks(record)))
            if input_status == "Input Done":
                success_records.append(record)
            elif input_status == "Failed":
                failed_records.append(record)
            table_rows.append([input_status, db_status, api_sync, api_match, record.emp_code, record.adjustment_name, self._description_for_record(record), self._adcode_for_record(record), f"{record.amount:g}", str(state.get("message", "")), str(state.get("tab_index", ""))])
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

    def _task_register_repository(self) -> TaskRegisterGatewayRepository:
        config = QueryGatewayConfig(
            base_url=self.config.query_gateway_base_url,
            api_key=self.config.query_gateway_api_key,
            server=self.config.query_gateway_server,
            database=self.config.query_gateway_database,
        )
        return TaskRegisterGatewayRepository(PlantwareDbPtrjGateway(config))

    def _loosefruit_repository(self) -> LoosefruitGatewayRepository:
        config = QueryGatewayConfig(
            base_url=self.config.query_gateway_base_url,
            api_key=self.config.query_gateway_api_key,
            server=self.config.query_gateway_server,
            database=self.config.query_gateway_database,
        )
        return LoosefruitGatewayRepository(PlantwareDbPtrjGateway(config))

    def _populate_division_dropdown(self) -> None:
        if self.divisions:
            for division in self.divisions:
                self.division_code.addItem(f"{division.code} - {division.label}", division.code)
        else:
            self.division_code.addItem(self.config.default_division_code, self.config.default_division_code)
        default_code = self.config.default_division_code.strip().upper()
        for index in range(self.division_code.count()):
            option = self._division_option_for_code(str(self.division_code.itemData(index) or ""))
            aliases = {alias.strip().upper() for alias in option.aliases} if option else set()
            if str(self.division_code.itemData(index)).upper() == default_code or default_code in aliases:
                self.division_code.setCurrentIndex(index)
                return

    def _selected_division_code(self) -> str:
        return str(self.division_code.currentData() or self.division_code.currentText()).split("-", 1)[0].strip().upper()

    def _division_option_for_code(self, code: str | None) -> DivisionOption | None:
        normalized = (code or "").strip().upper()
        if not normalized:
            return None
        for division in self.divisions:
            if division.code.strip().upper() == normalized:
                return division
            if any(alias.strip().upper() == normalized for alias in division.aliases):
                return division
        return None

    def _location_code_for_division(self, code: str | None) -> str:
        option = self._division_option_for_code(code)
        return option.effective_location_code if option else (code or "").strip().upper()

    def _session_code_for_division(self, code: str | None) -> str:
        option = self._division_option_for_code(code)
        return option.effective_session_code if option else (code or "").strip().upper()

    def _selected_location_code(self) -> str:
        return self._location_code_for_division(self._selected_division_code())

    def _selected_session_code(self) -> str:
        return self._session_code_for_division(self._selected_division_code())

    def _location_label_for_division(self, division: DivisionOption) -> str:
        location_code = division.effective_location_code
        location_option = self._division_option_for_code(location_code)
        location_label = location_option.label if location_option else location_code
        if location_code != division.code.strip().upper():
            return f"{location_code} - {location_label}"
        return division.label

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
            session_code = division.effective_session_code
            session_file = session_dir / f"session-{session_code}.json"
            status = "— None"
            age = ""
            saved = ""
            active = False
            if session_file.exists():
                try:
                    data = json.loads(session_file.read_text(encoding="utf-8"))
                    saved_at = self._parse_session_timestamp(str(data.get("savedAt", "")))
                    file_division = str(data.get("division") or session_code).strip().upper()
                    age_minutes = int((now - saved_at).total_seconds() / 60)
                    active = file_division == session_code and age_minutes < 240
                    if file_division != session_code:
                        status = f"Mismatch ({file_division})"
                    else:
                        status = "Active" if active else "Expired"
                    age = f"{age_minutes}m"
                    saved = saved_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                except (OSError, json.JSONDecodeError, ValueError):
                    status = "Invalid"
            results.append({
                "code": code,
                "label": self._location_label_for_division(division),
                "division_label": division.label,
                "session_code": session_code,
                "status": status,
                "age": age,
                "saved": saved,
                "active": active,
            })
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

    def _session_active_for_code(self, code: str | None) -> bool:
        normalized = (code or "").strip().upper()
        if not normalized:
            return False
        session_code = self._session_code_for_division(normalized) or normalized
        session_file = self._session_dir() / f"session-{session_code}.json"
        if not session_file.exists():
            return False
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            saved_at = self._parse_session_timestamp(str(data.get("savedAt", "")))
            file_division = str(data.get("division") or session_code).strip().upper()
            age_minutes = int((datetime.now(timezone.utc) - saved_at).total_seconds() / 60)
            return file_division == session_code and age_minutes < 240
        except (OSError, json.JSONDecodeError, ValueError):
            return False

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
            session_code = str(selected_status.get("session_code") or selected_code)
            suffix = f" via {session_code}" if session_code != selected_code else ""
            self.session_status_label.setText(f"Session ready for {selected_code}{suffix} (age: {selected_status['age']})")
        else:
            session_code = self._session_code_for_division(selected_code)
            suffix = f" parent {session_code}" if session_code and session_code != selected_code else selected_code
            self.session_status_label.setText(f"No active session for {selected_code} ({suffix}). Use Get Session or runner will do fresh login.")

    def _description_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        if record.adjustment_type == "AUTO_BUFFER" and category and category.description:
            return category.description
        name = record.adjustment_name.strip()
        return name[5:] if name.upper().startswith("AUTO ") else name

    def _adcode_for_record(self, record: ManualAdjustmentRecord) -> str:
        category = self.categories.by_key(record.category_key or str(self.category.currentData() or ""))
        is_auto_buffer = record.adjustment_type == "AUTO_BUFFER" or (record.category_key or "") in AUTO_BUFFER_CATEGORY_KEYS
        if is_auto_buffer and category and category.adcode:
            return category.adcode
        display_adcode = display_adcode_for_record(record)
        if display_adcode:
            return display_adcode
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

    def _db_status_for_record(self, record: ManualAdjustmentRecord) -> str:
        if self._sync_status_from_remarks(record).upper() == "SYNC":
            return "Already in DB"
        if self.fetch_verification_status.get("source") == "sync-status":
            row_id = self._sync_status_id_for_record(record)
            sync_payload = self.fetch_verification_status.get("sync_status_payload", {})
            row = sync_status_rows_by_id(sync_payload).get(row_id) if row_id is not None else None
            if row:
                api_sync, _ = sync_status_display_from_row(row)
                if api_sync == "SYNC":
                    return "Already in DB"
                if api_sync in {"DIFF", "MISMATCH"}:
                    return "DB Mismatch"
                if api_sync == "PARTIAL":
                    return "DB Mismatch"
                if api_sync in {"MISS", "MISSING", "NOT_FOUND"}:
                    return "Missing in DB"
                if api_sync in {"NO_SYNC_SEGMENT", "ERROR"}:
                    return "Verify Error"
            return "Not Checked"
        verified_status = self._fetch_verification_display(record).upper()
        if verified_status == "VERIFIED_MATCH":
            return "Already in DB"
        if verified_status == "VERIFIED_MISMATCH":
            return "DB Mismatch"
        if verified_status == "VERIFIED_NOT_FOUND":
            return "Missing in DB"
        if verified_status == "VERIFY_ERROR":
            return "Verify Error"
        return "Not Checked"

    def _record_is_miss(self, record: ManualAdjustmentRecord) -> bool:
        if record.category_key in PREMI_CATEGORY_KEYS and self.fetch_verification_status:
            return self._record_key(record) in self.premium_retry_record_keys
        verified_status = self._fetch_verification_display(record).upper()
        if verified_status in {"VERIFIED_MATCH", "VERIFIED_MISMATCH", "SYNC", "DIFF", "MISMATCH", "PARTIAL"}:
            return False
        if verified_status in {"VERIFIED_NOT_FOUND", "MISS", "MISSING", "NOT_FOUND"}:
            return True
        return record_is_stale_miss(record)

    def _record_key(self, record: ManualAdjustmentRecord) -> str:
        return record.record_key

    def _find_record(self, emp_code: str, adjustment_name: str = "", detail_key: str = "") -> ManualAdjustmentRecord | None:
        if detail_key:
            for record in self.records:
                if record.record_key == detail_key or record.detail_key == detail_key:
                    return record
        emp = emp_code.upper().strip()
        adj = adjustment_name.upper().strip()
        for record in self.records:
            if record.emp_code == emp and (not adj or record.adjustment_name.upper() == adj):
                return record
        return None

    def _reset_record_status(self) -> None:
        self.pending_sync_status_ids.clear()
        self.inflight_sync_status_ids.clear()
        self.sync_status_unavailable_message = ""
        for record in self.records:
            key = self._record_key(record)
            row = int(self.record_status.get(key, {}).get("row", -1))
            db_status = str(self.record_status.get(key, {}).get("db_status", "Not Checked"))
            api_sync = self._sync_status_from_remarks(record)
            api_match = self._fetch_verification_display(record) or self._match_status_from_remarks(record)
            self.record_status[key] = {
                "row": row,
                "input_status": "Pending",
                "db_status": db_status,
                "api_sync": api_sync,
                "api_match": api_match,
                "message": "",
            }
            if row >= 0:
                self.records_table.setItem(row, 0, QTableWidgetItem("Pending"))
                self.records_table.setItem(row, 1, QTableWidgetItem(db_status))
                self.records_table.setItem(row, 2, QTableWidgetItem(api_sync))
                self.records_table.setItem(row, 3, QTableWidgetItem(api_match))
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
        if hasattr(self, "fetch_task_register_duplicates_button"):
            self.fetch_task_register_duplicates_button.setEnabled(enabled)
        if hasattr(self, "fetch_loosefruit_duplicates_button"):
            self.fetch_loosefruit_duplicates_button.setEnabled(enabled)
        if hasattr(self, "delete_loosefruit_button"):
            self.delete_loosefruit_button.setEnabled(enabled and bool(self.duplicate_targets))
        if hasattr(self, "delete_duplicates_button"):
            self.delete_duplicates_button.setEnabled(enabled and bool(self.duplicate_targets))
        if hasattr(self, "fetch_reset_docid_button"):
            self.fetch_reset_docid_button.setEnabled(enabled)
        if hasattr(self, "run_reset_docid_delete_button"):
            self.run_reset_docid_delete_button.setEnabled(enabled and bool(self.reset_docid_targets))
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
        default_filter = self._default_filter_for_category_key(category_key) or category_key or "spsi"
        self.verify_filters.setText(default_filter)
        if hasattr(self, "duplicate_filters"):
            self.duplicate_month.setValue(self.period_month.value())
            self.duplicate_year.setValue(self.period_year.value())
            if hasattr(self, "task_register_loc_code"):
                self.task_register_loc_code.setText(self._selected_location_code())
            duplicate_index = self.duplicate_category.findData(category_key) if hasattr(self, "duplicate_category") else -1
            if duplicate_index >= 0:
                self.duplicate_category.setCurrentIndex(duplicate_index)
            else:
                self.duplicate_filters.setText(default_filter)

    def _sync_task_register_loc_code(self) -> None:
        if hasattr(self, "task_register_loc_code"):
            self.task_register_loc_code.setText(self._selected_location_code())

    def _default_filter_for_category_key(self, category_key: str) -> str:
        defaults = {
            "spsi": "spsi",
            "masa_kerja": "masa kerja",
            "tunjangan_jabatan": "jabatan",
            "pph21": "pph",
            "premi": "premi",
            "potongan_upah_kotor": "potongan",
            "koreksi": "koreksi",
            "potongan_upah_bersih": "potongan upah bersih",
            "premi_tunjangan": "premi",
            "premi_tiket": "premi",
            "premi_hari_raya": "premi",
            "premi_kehadiran": "premi",
        }
        return defaults.get(category_key, "")

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
        division_option = self._division_option_for_code(division_code)
        division_label = division_option.label if division_option else division_code
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
            session_division_code=self._session_code_for_division(division_code),
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

