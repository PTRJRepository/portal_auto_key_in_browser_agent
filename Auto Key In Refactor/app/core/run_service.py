from __future__ import annotations

from dataclasses import dataclass

from app.core.models import ManualAdjustmentRecord

DIVISION_EMP_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "P1A": ("A",),
    "PG1A": ("A",),
    "P1B": ("B",),
    "PG1B": ("B",),
    "P2A": ("C",),
    "PG2A": ("C",),
    "P2B": ("D",),
    "PG2B": ("D",),
    "DME": ("E",),
    "ARA": ("F",),
    "AB1": ("G",),
    "ARB1": ("G",),
    "AB2": ("H",),
    "ARB2": ("H",),
    "ARC": ("J",),
    "AREC": ("J",),
    "IJL": ("L",),
}


@dataclass(frozen=True)
class DbVerificationDecision:
    status: str
    skip_input: bool
    warning: str


def _format_amount(value: float) -> str:
    return f"{value:g}"


def evaluate_db_ptrj_status(expected_amount: float, actual_amount: float) -> DbVerificationDecision:
    if actual_amount == 0:
        return DbVerificationDecision("Missing in DB", False, "")
    if actual_amount == expected_amount:
        return DbVerificationDecision("Already in DB", True, "already exists in db_ptrj; skipped automatically")
    return DbVerificationDecision(
        "DB Mismatch",
        True,
        f"db_ptrj amount {_format_amount(actual_amount)} differs from expected {_format_amount(expected_amount)}; skipped automatically",
    )


def apply_row_limit(records: list[ManualAdjustmentRecord], row_limit: int | None) -> list[ManualAdjustmentRecord]:
    if row_limit is None or row_limit <= 0:
        return records
    return records[:row_limit]


def filter_by_category(records: list[ManualAdjustmentRecord], category_key: str | None) -> list[ManualAdjustmentRecord]:
    if not category_key:
        return records
    included_keys = {
        "premi": {"premi", "premi_tunjangan"},
    }.get(category_key, {category_key})
    return [record for record in records if record.category_key in included_keys]

def expected_emp_code_prefixes(division_code: str | None) -> tuple[str, ...]:
    code = (division_code or "").strip().upper()
    return DIVISION_EMP_CODE_PREFIXES.get(code, ())

def record_matches_division_prefix(record: ManualAdjustmentRecord, division_code: str | None) -> bool:
    prefixes = expected_emp_code_prefixes(division_code)
    if not prefixes:
        return True
    emp_code = (record.emp_code or "").strip().upper()
    return bool(emp_code) and emp_code.startswith(prefixes)

def division_mismatch_warning(record: ManualAdjustmentRecord, division_code: str | None) -> str:
    prefixes = expected_emp_code_prefixes(division_code)
    expected = "/".join(prefixes) if prefixes else "-"
    return (
        f"Skipped {record.emp_code or '-'} for division {(division_code or '-').strip().upper()}: "
        f"expected EmpCode prefix {expected}."
    )

def filter_records_by_division_prefix(
    records: list[ManualAdjustmentRecord],
    division_code: str | None,
) -> tuple[list[ManualAdjustmentRecord], list[ManualAdjustmentRecord]]:
    kept: list[ManualAdjustmentRecord] = []
    rejected: list[ManualAdjustmentRecord] = []
    for record in records:
        if record_matches_division_prefix(record, division_code):
            kept.append(record)
        else:
            rejected.append(record)
    return kept, rejected
