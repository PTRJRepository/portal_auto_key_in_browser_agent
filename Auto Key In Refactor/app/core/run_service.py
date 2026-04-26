from __future__ import annotations

from app.core.models import ManualAdjustmentRecord


def apply_row_limit(records: list[ManualAdjustmentRecord], row_limit: int | None) -> list[ManualAdjustmentRecord]:
    if row_limit is None or row_limit <= 0:
        return records
    return records[:row_limit]


def filter_by_category(records: list[ManualAdjustmentRecord], category_key: str | None) -> list[ManualAdjustmentRecord]:
    if not category_key:
        return records
    return [record for record in records if record.category_key == category_key]
