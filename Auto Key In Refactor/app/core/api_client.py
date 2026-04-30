from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.core.category_registry import CategoryRegistry
from app.core.models import (
    AutomationOption,
    DuplicateDocIdTarget,
    ManualAdjustmentRecord,
    normalize_automation_option,
    normalize_duplicate_target,
    normalize_record,
)


MANUAL_ADJUSTMENT_DIVISION_ALIASES = {
    "P1A": "PG1A",
    "P1B": "PG1B",
    "P2A": "PG2A",
    "P2B": "PG2B",
}
MANUAL_ADJUSTMENT_TYPES = {"PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH", "PENDAPATAN_LAINNYA", "MANUAL"}

def manual_adjustment_division_code(division_code: str | None, adjustment_type: str | None) -> str | None:
    if not division_code:
        return division_code
    code = division_code.strip().upper()
    type_tokens = {
        token.strip().upper()
        for token in (adjustment_type or "").split(",")
        if token.strip()
    }
    if type_tokens and type_tokens.issubset({"AUTO_BUFFER"}):
        return code
    if type_tokens & MANUAL_ADJUSTMENT_TYPES:
        return MANUAL_ADJUSTMENT_DIVISION_ALIASES.get(code, code)
    return code

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
            "division_code": manual_adjustment_division_code(self.division_code, self.adjustment_type),
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

    def get_automation_options(
        self,
        division_code: str | None = None,
        categories: list[str] | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[AutomationOption]:
        url = f"{self.base_url}/payroll/manual-adjustment/automation-options/by-api-key"
        params: dict[str, str] = {"limit": str(limit)}
        if division_code and division_code.strip():
            params["division_code"] = division_code.strip().upper()
        if categories:
            params["categories"] = ",".join(item.strip() for item in categories if item.strip())
        if search and search.strip():
            params["search"] = search.strip()
        response = requests.get(
            url,
            params=params,
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Automation options API returned success=false"
            raise RuntimeError(str(message))
        raw_options = payload.get("data", [])
        if not isinstance(raw_options, list):
            raise RuntimeError("Automation options API returned invalid data shape")
        return [normalize_automation_option(item) for item in raw_options if isinstance(item, dict)]

    def check_adtrans(self, period_month: int, period_year: int, emp_codes: list[str], filters: list[str]) -> list[dict[str, Any]]:
        payload = self.check_adtrans_report(period_month, period_year, filters, emp_codes=emp_codes)
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = data.get("totals") or data.get("data") or data.get("rows") or []
        if not isinstance(data, list):
            raise RuntimeError("ADTRANS check API returned invalid data shape")
        return [item for item in data if isinstance(item, dict)]

    def check_adtrans_report(
        self,
        period_month: int,
        period_year: int,
        filters: list[str],
        emp_codes: list[str] | None = None,
        division_code: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payroll/manual-adjustment/check-adtrans/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
            "filters": filters,
        }
        if division_code and division_code.strip():
            body["division_code"] = division_code.strip().upper()
        elif emp_codes is not None:
            body["emp_codes"] = emp_codes
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "ADTRANS check API returned success=false"
            raise RuntimeError(str(message))
        if not isinstance(payload, dict):
            raise RuntimeError("ADTRANS check API returned invalid payload shape")
        return payload

    def compare_adtrans(
        self,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payroll/manual-adjustment/compare-adtrans/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
            "division_code": division_code.strip().upper(),
        }
        if filters is not None:
            body["filters"] = filters
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Compare ADTRANS API returned success=false"
            raise RuntimeError(str(message))
        if not isinstance(payload, dict):
            raise RuntimeError("Compare ADTRANS API returned invalid payload shape")
        return payload

    def reverse_compare_adtrans(
        self,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payroll/manual-adjustment/reverse-compare-adtrans/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
            "division_code": division_code.strip().upper(),
        }
        if filters is not None:
            body["filters"] = filters
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Reverse compare ADTRANS API returned success=false"
            raise RuntimeError(str(message))
        if not isinstance(payload, dict):
            raise RuntimeError("Reverse compare ADTRANS API returned invalid payload shape")
        return payload

    def sync_adtrans(
        self,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str] | None = None,
        sync_mode: str = "MISMATCH_AND_MISSING",
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payroll/manual-adjustment/sync-adtrans/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
            "division_code": division_code.strip().upper(),
            "sync_mode": sync_mode,
        }
        if filters is not None:
            body["filters"] = filters
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Sync ADTRANS API returned success=false"
            raise RuntimeError(str(message))
        if not isinstance(payload, dict):
            raise RuntimeError("Sync ADTRANS API returned invalid payload shape")
        return payload

    def get_duplicate_delete_targets(self, period_month: int, period_year: int, division_code: str, filters: list[str]) -> list[DuplicateDocIdTarget]:
        payload = self.check_adtrans_report(period_month, period_year, filters, division_code=division_code)
        data = payload.get("data", {})
        report = data.get("duplicate_report", {}) if isinstance(data, dict) else payload.get("duplicate_report", {})
        duplicates = report.get("duplicates", []) if isinstance(report, dict) else []
        targets: list[DuplicateDocIdTarget] = []
        for duplicate in duplicates:
            if not isinstance(duplicate, dict):
                continue
            records = duplicate.get("records", [])
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                if str(record.get("action", "")).upper() != "DELETE_OLD":
                    continue
                target = normalize_duplicate_target(record, duplicate)
                if target.doc_id:
                    targets.append(target)
        return targets

    def _normalize(self, raw: dict[str, Any]) -> ManualAdjustmentRecord:
        category_key = self.categories.detect(
            str(raw.get("adjustment_name") or ""),
            str(raw.get("adjustment_type") or ""),
        )
        return normalize_record(raw, category_key)
