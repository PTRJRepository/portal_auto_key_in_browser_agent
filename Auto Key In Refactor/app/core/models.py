from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import re
from typing import Any


AD_CODE_RE = re.compile(r"\bAD\s*CODE\s*:\s*([^|\-]+)", re.IGNORECASE)

def extract_ad_code_from_remarks(remarks: str) -> str:
    match = AD_CODE_RE.search(remarks or "")
    return match.group(1).strip().upper() if match else ""

def divisioncode_from_gang(gang_code: str) -> str:
    compact = re.sub(r"\s+", "", gang_code or "").upper()
    if len(compact) < 2:
        return ""
    return f"{compact[0]} {compact[1]}"

def normalize_subblok_code(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", value or "").upper()

def normalize_detail_type(value: str, *, subblok: str = "", vehicle_code: str = "") -> str:
    normalized = (value or "").strip().lower()
    aliases = {
        "block": "blok",
        "subblok": "blok",
        "sub_block": "blok",
        "vehicle": "kendaraan",
        "veh": "kendaraan",
    }
    normalized = aliases.get(normalized, normalized)
    if not normalized and subblok:
        return "blok"
    if not normalized and vehicle_code:
        return "kendaraan"
    return normalized

@dataclass(frozen=True)
class AutomationOption:
    category: str
    adjustment_type: str
    adjustment_name: str
    ad_code: str
    description: str
    task_code: str
    task_desc: str
    base_task_code: str
    loc_code: str

def normalize_automation_option(raw: dict[str, Any]) -> AutomationOption:
    def text(*names: str) -> str:
        for name in names:
            value = raw.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    description = text("description", "doc_desc", "docDesc", "DocDesc", "ad_code_desc", "adCodeDesc", "ADCodeDesc")
    adjustment_name = text("adjustment_name") or description
    return AutomationOption(
        category=text("category").lower(),
        adjustment_type=text("adjustment_type").upper(),
        adjustment_name=adjustment_name,
        ad_code=text("ad_code", "adCode", "ADCode").upper(),
        description=description or adjustment_name,
        task_code=text("task_code", "taskCode", "TaskCode"),
        task_desc=text("task_desc", "taskDesc", "TaskDesc"),
        base_task_code=text("base_task_code", "baseTaskCode", "BaseTaskCode"),
        loc_code=text("loc_code", "locCode", "LocCode").upper(),
    )


@dataclass(frozen=True)
class ManualAdjustmentRecord:
    id: int | None
    period_month: int | None
    period_year: int | None
    emp_code: str
    gang_code: str
    division_code: str
    adjustment_type: str
    adjustment_name: str
    amount: float
    remarks: str
    emp_name: str = ""
    nik: str = ""
    category_key: str | None = None
    ad_code: str = ""
    ad_code_desc: str = ""
    description: str = ""
    task_code: str = ""
    task_desc: str = ""
    base_task_code: str = ""
    loc_code: str = ""
    automation_category: str = ""
    estate: str = ""
    divisioncode: str = ""
    detail_type: str = ""
    subblok: str = ""
    subblok_raw: str = ""
    jumlah: float = 0.0
    expense_code: str = ""
    vehicle_code: str = ""
    vehicle_expense_code: str = ""
    transaction_index: int | None = None
    adjustment_id: int | None = None
    detail_key: str = ""

    @property
    def record_key(self) -> str:
        if self.detail_key:
            return self.detail_key
        detail = self.subblok or self.vehicle_code or str(self.transaction_index or "")
        return f"{self.period_month}:{self.period_year}:{self.emp_code}:{self.adjustment_name}:{detail}:{self.amount:g}"

    def to_runner_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_record(raw: dict[str, Any], category_key: str | None = None) -> ManualAdjustmentRecord:
    def text(*names: str) -> str:
        for name in names:
            value = raw.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def number(*names: str) -> float:
        for name in names:
            value = raw.get(name)
            if value in (None, ""):
                continue
            try:
                return abs(float(value or 0))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def integer_or_none(*names: str) -> int | None:
        for name in names:
            value = raw.get(name)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    remarks = text("remarks")
    adjustment_name = text("adjustment_name")
    description = text("description", "doc_desc", "docDesc", "DocDesc", "ad_code_desc", "adCodeDesc", "ADCodeDesc")
    ad_code_desc = text("ad_code_desc", "adCodeDesc", "ADCodeDesc")
    adjustment_type = text("adjustment_type").upper()
    if adjustment_type == "PREMI" and adjustment_name:
        description = adjustment_name
    ad_code = text("ad_code", "adCode", "ADCode").upper() or extract_ad_code_from_remarks(remarks)
    gang_code = text("gang_code").upper()
    estate = text("estate", "estate_code", "estateCode", "Estate").upper()
    raw_division_code = text("division_code", "divisionCode", "DivisionCode").upper()
    division_code = estate or raw_division_code
    divisioncode = text("divisioncode", "Divisioncode", "field_division_code", "fieldDivisionCode").upper()
    if not divisioncode and estate and raw_division_code and raw_division_code != estate:
        divisioncode = raw_division_code
    if not divisioncode:
        divisioncode = divisioncode_from_gang(gang_code)
    subblok_raw = text("subblok_raw", "subblokRaw", "sub_block_raw", "subBlockRaw")
    subblok = normalize_subblok_code(text("subblok", "sub_block", "subBlock") or subblok_raw)
    expense_code = text("expense_code", "expenseCode", "exp_code", "expCode").upper()
    vehicle_code = text(
        "vehicle_code",
        "vehicleCode",
        "veh_code",
        "vehCode",
        "kendaraan",
        "vehicle",
        "nomor_kendaraan",
        "NOMOR_KENDARAAN",
        "nomorKendaraan",
        "no_kendaraan",
        "NoKendaraan",
        "vehicle_number",
        "vehicleNumber",
    ).upper()
    vehicle_expense_code = text(
        "vehicle_expense_code",
        "vehicleExpenseCode",
        "veh_expense_code",
        "vehExpenseCode",
        "veh_exp_code",
        "vehExpCode",
        "kendaraan_expense_code",
    ).upper()
    detail_type = normalize_detail_type(text("detail_type", "detailType", "input_type", "inputType"), subblok=subblok, vehicle_code=vehicle_code)
    if not vehicle_expense_code and (detail_type == "kendaraan" or vehicle_code):
        vehicle_expense_code = expense_code
    amount = number("amount", "jumlah")
    jumlah = number("jumlah", "amount")
    transaction_index = integer_or_none("transaction_index", "transactionIndex")
    adjustment_id = integer_or_none("adjustment_id", "adjustmentId", "id")
    detail_key_parts = [
        str(raw.get("period_month") or ""),
        str(raw.get("period_year") or ""),
        text("emp_code").upper(),
        adjustment_name.upper(),
        str(adjustment_id or ""),
        str(transaction_index or ""),
        detail_type,
        subblok or vehicle_code,
        f"{amount:g}",
    ]
    detail_key = "|".join(part for part in detail_key_parts if part)
    return ManualAdjustmentRecord(
        id=integer_or_none("id"),
        period_month=integer_or_none("period_month"),
        period_year=integer_or_none("period_year"),
        emp_code=text("emp_code").upper(),
        gang_code=gang_code,
        division_code=division_code,
        adjustment_type=adjustment_type,
        adjustment_name=adjustment_name,
        amount=amount,
        remarks=remarks,
        emp_name=text("emp_name", "empName", "EmpName", "employee_name", "employeeName", "EmployeeName"),
        nik=text("nik", "NIK", "new_ic_no", "newICNo", "NewICNo", "NewIcNo"),
        category_key=category_key,
        ad_code=ad_code,
        ad_code_desc=ad_code_desc,
        description=description,
        task_code=text("task_code", "taskCode", "TaskCode"),
        task_desc=text("task_desc", "taskDesc", "TaskDesc", "ad_code_desc", "adCodeDesc", "ADCodeDesc"),
        base_task_code=text("base_task_code", "baseTaskCode", "BaseTaskCode"),
        loc_code=text("loc_code", "locCode", "LocCode").upper(),
        automation_category=text("category").lower(),
        estate=estate or division_code,
        divisioncode=divisioncode,
        detail_type=detail_type,
        subblok=subblok,
        subblok_raw=subblok_raw,
        jumlah=jumlah,
        expense_code=expense_code,
        vehicle_code=vehicle_code,
        vehicle_expense_code=vehicle_expense_code,
        transaction_index=transaction_index,
        adjustment_id=adjustment_id,
        detail_key=detail_key,
    )


def enrich_records_with_automation_options(
    records: list[ManualAdjustmentRecord],
    options: list[AutomationOption],
) -> list[ManualAdjustmentRecord]:
    if not records or not options:
        return records

    option_index: dict[tuple[str, str], AutomationOption] = {}
    for option in options:
        for name in {option.adjustment_name, option.description}:
            normalized_name = " ".join(name.upper().split())
            if normalized_name:
                option_index[(option.adjustment_type, normalized_name)] = option

    enriched: list[ManualAdjustmentRecord] = []
    for record in records:
        normalized_name = " ".join(record.adjustment_name.upper().split())
        option = option_index.get((record.adjustment_type, normalized_name))
        if not option:
            enriched.append(record)
            continue
        enriched.append(
            replace(
                record,
                ad_code=record.ad_code or option.ad_code,
                ad_code_desc=record.ad_code_desc or option.task_desc,
                description=record.description or option.description,
                task_code=record.task_code or option.task_code,
                task_desc=record.task_desc or option.task_desc,
                base_task_code=record.base_task_code or option.base_task_code,
                loc_code=record.loc_code or option.loc_code,
                automation_category=record.automation_category or option.category,
            )
        )
    return enriched

@dataclass(frozen=True)
class DuplicateDocIdTarget:
    master_id: str
    doc_id: str
    doc_date: str
    emp_code: str
    emp_name: str
    doc_desc: str
    amount: float | None
    action: str
    keep_doc_id: str
    category: str
    raw: dict[str, Any]

    def to_runner_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_duplicate_target(raw_record: dict[str, Any], duplicate: dict[str, Any] | None = None) -> DuplicateDocIdTarget:
    duplicate = duplicate or {}

    def text(*names: str) -> str:
        for name in names:
            value = raw_record.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def duplicate_text(*names: str) -> str:
        for name in names:
            value = duplicate.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def number(*names: str) -> float | None:
        for name in names:
            value = raw_record.get(name)
            if value not in (None, ""):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    return DuplicateDocIdTarget(
        master_id=text("master_id", "id", "MasterID"),
        doc_id=text("doc_id", "docId", "DocID"),
        doc_date=text("doc_date", "docDate", "DocDate"),
        emp_code=duplicate_text("emp_code", "empCode", "EmpCode").upper(),
        emp_name=duplicate_text("emp_name", "empName", "EmpName"),
        doc_desc=text("doc_desc", "docDesc", "DocDesc") or duplicate_text("category"),
        amount=number("amount", "Amount"),
        action=text("action", "Action").upper(),
        keep_doc_id=duplicate_text("keep_doc_id", "keepDocId", "keep_docID"),
        category=duplicate_text("category", "category_key", "filter"),
        raw=raw_record,
    )


@dataclass(frozen=True)
class RunPayload:
    period_month: int
    period_year: int
    division_code: str
    gang_code: str | None
    emp_code: str | None
    adjustment_type: str | None
    adjustment_name: str | None
    category_key: str
    runner_mode: str
    max_tabs: int
    headless: bool
    only_missing_rows: bool
    row_limit: int | None
    records: list[ManualAdjustmentRecord]
    operation: str = "input"
    duplicate_targets: list[DuplicateDocIdTarget] | None = None
    delete_dry_run: bool = True

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["records"] = [record.to_runner_dict() for record in self.records]
        data["duplicate_targets"] = [target.to_runner_dict() for target in self.duplicate_targets or []]
        return data
