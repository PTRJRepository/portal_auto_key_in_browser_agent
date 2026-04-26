from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


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
    category_key: str | None = None

    @property
    def record_key(self) -> str:
        return f"{self.period_month}:{self.period_year}:{self.emp_code}:{self.adjustment_name}"

    def to_runner_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_record(raw: dict[str, Any], category_key: str | None = None) -> ManualAdjustmentRecord:
    def text(name: str) -> str:
        value = raw.get(name)
        return "" if value is None else str(value).strip()

    def number(name: str) -> float:
        value = raw.get(name, 0)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def integer_or_none(name: str) -> int | None:
        value = raw.get(name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return ManualAdjustmentRecord(
        id=integer_or_none("id"),
        period_month=integer_or_none("period_month"),
        period_year=integer_or_none("period_year"),
        emp_code=text("emp_code").upper(),
        gang_code=text("gang_code").upper(),
        division_code=text("division_code").upper(),
        adjustment_type=text("adjustment_type").upper(),
        adjustment_name=text("adjustment_name"),
        amount=number("amount"),
        remarks=text("remarks"),
        category_key=category_key,
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

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["records"] = [record.to_runner_dict() for record in self.records]
        return data
