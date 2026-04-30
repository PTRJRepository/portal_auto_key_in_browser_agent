from __future__ import annotations

from dataclasses import dataclass

from app.core.models import ManualAdjustmentRecord


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
