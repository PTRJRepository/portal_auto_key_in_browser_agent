from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import requests

from app.core.category_registry import CategoryRegistry
from app.core.models import (
    AutomationOption,
    DuplicateDocIdTarget,
    ManualAdjustmentRecord,
    metadata_detail_items,
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
MANUAL_ADJUSTMENT_OPTION_TYPES = "PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH"

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

def manual_adjustment_option_type(adjustment_type: str | None) -> str | None:
    if not adjustment_type or not adjustment_type.strip():
        return None
    tokens = [
        token.strip().upper()
        for token in adjustment_type.split(",")
        if token.strip()
    ]
    aliases = {
        "MANUAL": MANUAL_ADJUSTMENT_OPTION_TYPES,
        "KOREKSI": "POTONGAN_KOTOR",
        "POTONGAN_UPAH_BERSIH": "POTONGAN_BERSIH",
    }
    mapped: list[str] = []
    for token in tokens:
        replacement = aliases.get(token, token)
        mapped.extend(part for part in replacement.split(",") if part)
    return ",".join(dict.fromkeys(mapped))

@dataclass(frozen=True)
class ManualAdjustmentQuery:
    period_month: int
    period_year: int
    division_code: str | None = None
    gang_code: str | None = None
    emp_code: str | None = None
    adjustment_type: str | None = None
    adjustment_name: str | None = None
    view: str | None = None
    metadata_only: bool | None = None

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
            "view": self.view,
        }
        for key, value in optional.items():
            if value and value.strip():
                values[key] = value.strip()
        if self.metadata_only is not None:
            values["metadata_only"] = "true" if self.metadata_only else "false"
        return values

    def with_grouped_premium_details(self) -> "ManualAdjustmentQuery":
        return replace(self, adjustment_type="PREMI", view="grouped", metadata_only=True)

    def uses_grouped_view(self) -> bool:
        return (self.view or "").strip().lower() == "grouped"

    def requests_premium(self) -> bool:
        tokens = {
            token.strip().upper()
            for token in (self.adjustment_type or "").split(",")
            if token.strip()
        }
        return "PREMI" in tokens


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
        if query.uses_grouped_view() or str(payload.get("view") or "").strip().lower() == "grouped":
            return self._normalize_grouped_premium_records(raw_records, query)
        return [self._normalize(item) for item in self._flatten_detail_records(raw_records)]

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

    def get_adjustment_name_options(
        self,
        period_month: int | None = None,
        period_year: int | None = None,
        division_code: str | None = None,
        gang_code: str | None = None,
        emp_code: str | None = None,
        adjustment_type: str | None = None,
        metadata_only: bool | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> list[AutomationOption]:
        url = f"{self.base_url}/payroll/manual-adjustment/adjustment-name-options/by-api-key"
        params: dict[str, str] = {"limit": str(limit)}
        if period_month is not None:
            params["period_month"] = str(period_month)
        if period_year is not None:
            params["period_year"] = str(period_year)
        if division_code and division_code.strip():
            params["division_code"] = division_code.strip().upper()
        if gang_code and gang_code.strip():
            params["gang_code"] = gang_code.strip().upper()
        if emp_code and emp_code.strip():
            params["emp_code"] = emp_code.strip().upper()
        normalized_type = manual_adjustment_option_type(adjustment_type)
        if normalized_type:
            params["adjustment_type"] = normalized_type
        if metadata_only is not None:
            params["metadata_only"] = "true" if metadata_only else "false"
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
            message = payload.get("message") or payload.get("error") or "Adjustment name options API returned success=false"
            raise RuntimeError(str(message))
        return self._normalize_adjustment_name_options(payload)

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

    def sync_status(
        self,
        period_month: int,
        period_year: int,
        division_code: str | None = None,
        gang_code: str | None = None,
        emp_code: str | None = None,
        adjustment_type: str | None = None,
        adjustment_name: str | None = None,
        ids: list[int] | None = None,
        sync_status: str = "SYNC",
        only_if_adtrans_exists: bool = True,
        dry_run: bool = True,
        updated_by: str = "browser_automation",
        limit: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payroll/manual-adjustment/sync-status/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
            "sync_status": sync_status,
            "only_if_adtrans_exists": only_if_adtrans_exists,
            "dry_run": dry_run,
            "updated_by": updated_by,
        }
        optional = {
            "division_code": division_code.strip().upper() if division_code and division_code.strip() else None,
            "gang_code": gang_code.strip().upper() if gang_code and gang_code.strip() else None,
            "emp_code": emp_code.strip().upper() if emp_code and emp_code.strip() else None,
            "adjustment_type": adjustment_type.strip().upper() if adjustment_type and adjustment_type.strip() else None,
            "adjustment_name": adjustment_name.strip() if adjustment_name and adjustment_name.strip() else None,
        }
        for key, value in optional.items():
            if value:
                body[key] = value
        if ids:
            body["ids"] = ids
        if limit is not None:
            body["limit"] = limit
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "Sync status API returned success=false"
            raise RuntimeError(str(message))
        if not isinstance(payload, dict):
            raise RuntimeError("Sync status API returned invalid payload shape")
        return payload

    def get_adtrans_doc_id_delete_targets(
        self,
        period_month: int,
        period_year: int,
        division_code: str | None = None,
        filters: list[str] | None = None,
        adjustment_type: str | None = None,
        adjustment_name: str | None = None,
        category_key: str = "",
        emp_code: str | None = None,
        doc_desc: str | None = None,
    ) -> list[DuplicateDocIdTarget]:
        url = f"{self.base_url}/payroll/manual-adjustment/adtrans-doc-ids/by-api-key"
        body: dict[str, Any] = {
            "period_month": period_month,
            "period_year": period_year,
        }
        if emp_code and emp_code.strip():
            body["emp_codes"] = [emp_code.strip().upper()]
        elif division_code and division_code.strip():
            body["division_code"] = division_code.strip().upper()
        clean_filters = [item.strip() for item in filters or [] if item.strip()]
        if clean_filters:
            body["filters"] = clean_filters
        if adjustment_type and adjustment_type.strip():
            body["adjustment_type"] = adjustment_type.strip().upper()
        if adjustment_name and adjustment_name.strip():
            body["adjustment_name"] = adjustment_name.strip()
        if doc_desc and doc_desc.strip():
            body["doc_desc"] = doc_desc.strip()
        response = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            message = payload.get("message") or payload.get("error") or "ADTRANS DocID API returned success=false"
            raise RuntimeError(str(message))
        doc_ids = payload.get("doc_ids")
        if not isinstance(doc_ids, list):
            data = payload.get("data", {})
            doc_ids = data.get("doc_ids", []) if isinstance(data, dict) else []
        if not isinstance(doc_ids, list):
            raise RuntimeError("ADTRANS DocID API returned invalid doc_ids shape")
        label = (doc_desc or adjustment_name or ", ".join(clean_filters) or adjustment_type or "ADTRANS").strip()
        targets: list[DuplicateDocIdTarget] = []
        seen: set[str] = set()
        for value in doc_ids:
            doc_id = str(value or "").strip()
            if not doc_id or doc_id.upper() in seen:
                continue
            seen.add(doc_id.upper())
            targets.append(DuplicateDocIdTarget(
                master_id="",
                doc_id=doc_id,
                doc_date="",
                emp_code=(emp_code or "").strip().upper(),
                emp_name="",
                doc_desc=label,
                amount=None,
                action="DELETE_RECORD",
                keep_doc_id="",
                category=category_key,
                raw={"source": "adtrans-doc-ids", "doc_id": doc_id, "action": "DELETE_RECORD"},
            ))
        return targets

    def get_duplicate_delete_targets(self, period_month: int, period_year: int, division_code: str, filters: list[str]) -> list[DuplicateDocIdTarget]:
        payload = self.check_adtrans_report(period_month, period_year, filters, division_code=division_code)
        data = payload.get("data", {})
        report = data.get("duplicate_report", {}) if isinstance(data, dict) else payload.get("duplicate_report", {})
        duplicates = report.get("duplicates", []) if isinstance(report, dict) else []
        targets: list[DuplicateDocIdTarget] = []
        premium_filter = any(str(item).strip().lower() == "premi" for item in filters)
        for duplicate in duplicates:
            if not isinstance(duplicate, dict):
                continue
            if premium_filter or str(duplicate.get("category") or "").strip().lower() == "premi":
                targets.extend(self._premium_duplicate_delete_targets(duplicate))
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

    def _premium_duplicate_delete_targets(self, duplicate: dict[str, Any]) -> list[DuplicateDocIdTarget]:
        records = [record for record in duplicate.get("records", []) if isinstance(record, dict)]
        groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for record in records:
            doc_desc = " ".join(str(record.get("doc_desc") or record.get("docDesc") or record.get("DocDesc") or "").upper().split())
            amount_units = int(round(float(record.get("amount") or record.get("Amount") or 0) * 100))
            key = (doc_desc, amount_units)
            if doc_desc:
                groups.setdefault(key, []).append(record)

        targets: list[DuplicateDocIdTarget] = []
        for group_records in groups.values():
            if len(group_records) < 2:
                continue
            ordered = sorted(group_records, key=self._duplicate_record_sort_key)
            keep = ordered[-1]
            keep_doc_id = str(keep.get("doc_id") or keep.get("docId") or keep.get("DocID") or "").strip()
            group_duplicate = dict(duplicate)
            group_duplicate["keep_doc_id"] = keep_doc_id
            for record in ordered[:-1]:
                raw_record = dict(record)
                raw_record["action"] = "DELETE_OLD"
                target = normalize_duplicate_target(raw_record, group_duplicate)
                if target.doc_id:
                    targets.append(target)
        return targets

    def _duplicate_record_sort_key(self, record: dict[str, Any]) -> tuple[int, str]:
        row_id = str(record.get("id") or record.get("master_id") or record.get("MasterID") or "").strip()
        try:
            numeric_id = int(row_id)
        except ValueError:
            numeric_id = 0
        doc_id = str(record.get("doc_id") or record.get("docId") or record.get("DocID") or "").strip()
        return (numeric_id, doc_id)

    def _normalize(self, raw: dict[str, Any]) -> ManualAdjustmentRecord:
        category_key = self.categories.detect(
            str(raw.get("adjustment_name") or ""),
            str(raw.get("adjustment_type") or ""),
        )
        return normalize_record(raw, category_key)

    def _flatten_detail_records(self, raw_records: list[Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            details = metadata_detail_items(raw)
            if not details:
                flattened.append(raw)
                continue
            parent = {
                key: value
                for key, value in raw.items()
                if key not in {"metadata", "metadata_json", "detail_items"}
            }
            parent_id = raw.get("id")
            for index, detail in enumerate(details, start=1):
                detail_division_code = detail.get("division_code") or detail.get("divisionCode")
                merged = {**parent, **detail, "transaction_index": detail.get("transaction_index", index)}
                parent_location = parent.get("estate") or parent.get("estate_code") or parent.get("division_code")
                if detail_division_code not in (None, "") and parent_location not in (None, ""):
                    merged.setdefault("divisioncode", detail_division_code)
                    merged["division_code"] = parent_location
                if parent_id not in (None, ""):
                    merged["id"] = parent_id
                    merged.setdefault("adjustment_id", parent_id)
                flattened.append(merged)
        return flattened

    def _normalize_adjustment_name_options(self, payload: dict[str, Any]) -> list[AutomationOption]:
        raw_options: list[Any] = []
        by_type = payload.get("by_type", {})
        if isinstance(by_type, dict):
            for items in by_type.values():
                if isinstance(items, list):
                    raw_options.extend(items)
        data = payload.get("data", [])
        if isinstance(data, list):
            raw_options.extend(data)
        if not raw_options:
            names_by_type = payload.get("adjustment_names_by_type", {})
            if isinstance(names_by_type, dict):
                for adjustment_type, names in names_by_type.items():
                    if not isinstance(names, list):
                        continue
                    for name in names:
                        raw_options.append({
                            "adjustment_type": adjustment_type,
                            "adjustment_name": name,
                            "description": name,
                        })

        options: list[AutomationOption] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_options:
            if not isinstance(item, dict):
                continue
            option = normalize_automation_option(item)
            key = (option.adjustment_type, option.adjustment_name.upper(), option.ad_code)
            if key in seen:
                continue
            seen.add(key)
            options.append(option)
        return options

    def _normalize_grouped_premium_records(
        self,
        divisions: list[Any],
        query: ManualAdjustmentQuery,
    ) -> list[ManualAdjustmentRecord]:
        records: list[ManualAdjustmentRecord] = []
        for division in divisions:
            if not isinstance(division, dict):
                continue
            estate = self._text(division, "estate", "estate_code", "division_code")
            gangs = division.get("gangs", [])
            if not isinstance(gangs, list):
                continue
            for gang in gangs:
                if not isinstance(gang, dict):
                    continue
                gang_code = self._text(gang, "gang_code")
                employees = gang.get("employees", [])
                if not isinstance(employees, list):
                    continue
                for employee in employees:
                    if not isinstance(employee, dict):
                        continue
                    employee_context = {
                        "period_month": query.period_month,
                        "period_year": query.period_year,
                        "emp_code": self._text(employee, "emp_code"),
                        "nik": self._text(employee, "nik", "new_ic_no", "newICNo", "NewICNo"),
                        "emp_name": self._text(employee, "emp_name", "empName", "employee_name"),
                        "gang_code": self._text(employee, "gang_code") or gang_code,
                        "estate": self._text(employee, "estate", "estate_code") or estate,
                        "division_code": self._text(employee, "estate", "estate_code") or estate,
                    }
                    for transaction in self._employee_premium_transactions(employee):
                        transaction_divisioncode = self._premium_transaction_divisioncode(transaction, employee_context)
                        transaction_estate = self._text(transaction, "estate", "estate_code")
                        raw = {**employee_context, **transaction}
                        raw["gang_code"] = self._text(raw, "gang_code") or employee_context["gang_code"]
                        raw["estate"] = transaction_estate or self._text(raw, "estate", "estate_code") or employee_context["estate"]
                        raw["divisioncode"] = self._text(raw, "divisioncode", "field_division_code") or transaction_divisioncode
                        raw["division_code"] = raw["estate"] or employee_context["division_code"]
                        category_key = self.categories.detect(
                            str(raw.get("adjustment_name") or ""),
                            str(raw.get("adjustment_type") or "PREMI"),
                        )
                        records.append(normalize_record(raw, category_key))
        return records

    def _employee_premium_transactions(self, employee: dict[str, Any]) -> list[dict[str, Any]]:
        transactions = employee.get("premium_transactions", [])
        if isinstance(transactions, list) and transactions:
            return [item for item in transactions if isinstance(item, dict)]

        flattened: list[dict[str, Any]] = []
        premiums = employee.get("premiums", [])
        adjustments = employee.get("adjustments", [])
        grouped_rows = premiums if isinstance(premiums, list) and premiums else adjustments if isinstance(adjustments, list) else []
        if not grouped_rows:
            return flattened
        for premium in grouped_rows:
            if not isinstance(premium, dict):
                continue
            detail_items = metadata_detail_items(premium)
            if not detail_items:
                continue
            parent = {
                key: value
                for key, value in premium.items()
                if key not in {"metadata", "metadata_json", "detail_items"}
            }
            for index, detail in enumerate(detail_items, start=1):
                if not isinstance(detail, dict):
                    continue
                flattened.append({**parent, **detail, "transaction_index": detail.get("transaction_index", index)})
        return flattened

    def _premium_transaction_divisioncode(
        self,
        transaction: dict[str, Any],
        employee_context: dict[str, str],
    ) -> str:
        explicit = self._text(transaction, "divisioncode", "Divisioncode", "field_division_code", "fieldDivisionCode")
        if explicit:
            return explicit
        raw_division = self._text(transaction, "division_code", "divisionCode", "DivisionCode")
        if not raw_division:
            return ""
        estate = (
            self._text(transaction, "estate", "estate_code", "estateCode")
            or employee_context.get("estate", "")
            or employee_context.get("division_code", "")
        ).strip().upper()
        normalized = raw_division.strip().upper()
        return "" if estate and normalized == estate else raw_division

    def _text(self, raw: dict[str, Any], *names: str) -> str:
        for name in names:
            value = raw.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return ""
