from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.core.category_registry import CategoryRegistry
from app.core.models import ManualAdjustmentRecord, normalize_record


@dataclass(frozen=True)
class ManualAdjustmentQuery:
    period_month: int
    period_year: int
    division_code: str | None = None
    gang_code: str | None = None
    emp_code: str | None = None
    adjustment_type: str | None = None
    adjustment_name: str | None = None

    def params(self) -> dict[str, str]:
        values: dict[str, str] = {
            "period_month": str(self.period_month),
            "period_year": str(self.period_year),
        }
        optional = {
            "division_code": self.division_code,
            "gang_code": self.gang_code,
            "emp_code": self.emp_code,
            "adjustment_type": self.adjustment_type,
            "adjustment_name": self.adjustment_name,
        }
        for key, value in optional.items():
            if value and value.strip():
                values[key] = value.strip()
        return values


class ManualAdjustmentApiClient:
    def __init__(self, base_url: str, api_key: str, categories: CategoryRegistry, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.categories = categories
        self.timeout_seconds = timeout_seconds

    def get_adjustments(self, query: ManualAdjustmentQuery) -> list[ManualAdjustmentRecord]:
        url = f"{self.base_url}/payroll/manual-adjustment/by-api-key"
        response = requests.get(
            url,
            params=query.params(),
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Manual adjustment API returned success=false"
            raise RuntimeError(str(message))
        raw_records = payload.get("data", [])
        if not isinstance(raw_records, list):
            raise RuntimeError("Manual adjustment API returned invalid data shape")
        return [self._normalize(item) for item in raw_records if isinstance(item, dict)]

    def _normalize(self, raw: dict[str, Any]) -> ManualAdjustmentRecord:
        category_key = self.categories.detect(
            str(raw.get("adjustment_name") or ""),
            str(raw.get("adjustment_type") or ""),
        )
        return normalize_record(raw, category_key)
