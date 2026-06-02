from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests


DEFAULT_STAGING_COMPARISON_PATH = "/backend/upah/api/staging/staging-comparison"


def _frontend_to_backend_source(source: str) -> str:
    if source.endswith("/upah/staging-comparison") and ":3001" in source:
        return source.replace(":3001", ":8002").replace("/upah/staging-comparison", DEFAULT_STAGING_COMPARISON_PATH)
    return source


@dataclass(frozen=True)
class LoosefruitStagingRow:
    emp_code: str
    emp_name: str
    gang: str
    gang_name: str
    divisi: str
    estate: str
    staging_brondol: float
    plantware_brondol: float
    selisih: float


@dataclass(frozen=True)
class LoosefruitStagingTotals:
    staging_brondol: float
    plantware_brondol: float
    selisih: float


@dataclass(frozen=True)
class LoosefruitStagingComparison:
    periode: str
    rows: list[LoosefruitStagingRow]
    totals: LoosefruitStagingTotals
    source_url: str


def loosefruit_staging_comparison_url(base_or_url: str, periode: str, division: str | None = None, gang: str | None = None) -> str:
    source = _frontend_to_backend_source((base_or_url or "http://localhost:8002").strip().rstrip("/"))
    query_items = {"periode": periode}
    if division:
        query_items["division"] = division.strip().upper()
    if gang:
        query_items["gang"] = gang.strip().upper()
    query = urlencode(query_items)
    if source.endswith("/upah/staging-comparison"):
        source = source.replace("/upah/staging-comparison", DEFAULT_STAGING_COMPARISON_PATH)
    if source.endswith("/api/staging/staging-comparison") or source.endswith("/backend/upah/api/staging/staging-comparison"):
        return f"{source}?{query}"
    return f"{source}{DEFAULT_STAGING_COMPARISON_PATH}?{query}"


def numeric_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    return float(text) if text else 0.0


def normalize_loosefruit_staging_row(row: dict[str, Any]) -> LoosefruitStagingRow:
    return LoosefruitStagingRow(
        emp_code=str(row.get("emp_code") or row.get("EmpCode") or "").strip().upper(),
        emp_name=str(row.get("emp_name") or row.get("EmpName") or "").strip(),
        gang=str(row.get("gang") or row.get("gang_code") or row.get("Gang") or "").strip().upper(),
        gang_name=str(row.get("gang_name") or row.get("GangName") or "").strip(),
        divisi=str(row.get("divisi") or row.get("division") or row.get("Division") or "").strip().upper(),
        estate=str(row.get("estate") or row.get("loc_code") or row.get("LocCode") or row.get("division") or "").strip().upper(),
        staging_brondol=numeric_value(row.get("staging_brondol") if row.get("staging_brondol") is not None else row.get("staging_bunches")),
        plantware_brondol=numeric_value(row.get("plantware_brondol") if row.get("plantware_brondol") is not None else row.get("prod_mt")),
        selisih=numeric_value(row.get("selisih") if row.get("selisih") is not None else row.get("delta")),
    )


def normalize_loosefruit_staging_payload(payload: dict[str, Any], source_url: str) -> LoosefruitStagingComparison:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows_raw = data.get("rows", []) if isinstance(data, dict) else []
    if not isinstance(rows_raw, list):
        raise ValueError("staging-comparison response data.rows must be a list")
    rows = [normalize_loosefruit_staging_row(row) for row in rows_raw if isinstance(row, dict)]
    totals_raw = data.get("totals", {}) if isinstance(data, dict) else {}
    if not isinstance(totals_raw, dict):
        totals_raw = {}
    totals = LoosefruitStagingTotals(
        staging_brondol=numeric_value(totals_raw.get("staging_brondol")),
        plantware_brondol=numeric_value(totals_raw.get("plantware_brondol")),
        selisih=numeric_value(totals_raw.get("selisih")),
    )
    periode = str(data.get("periode") or payload.get("periode") or "").strip() if isinstance(data, dict) else ""
    return LoosefruitStagingComparison(periode=periode, rows=rows, totals=totals, source_url=source_url)


def eligible_loosefruit_rows(rows: list[LoosefruitStagingRow], estate: str | None = None) -> list[LoosefruitStagingRow]:
    estate_filter = (estate or "").strip().upper()
    return [
        row for row in rows
        if row.selisih > 0
        and row.emp_code
        and (not estate_filter or row.estate == estate_filter)
    ]


def fetch_loosefruit_staging_comparison(base_or_url: str, periode: str, timeout_seconds: int = 30, division: str | None = None, gang: str | None = None) -> LoosefruitStagingComparison:
    url = loosefruit_staging_comparison_url(base_or_url, periode, division=division, gang=gang)
    response = requests.get(url, timeout=timeout_seconds)
    if not response.ok:
        raise RuntimeError(f"staging-comparison HTTP {response.status_code}: {response.text[:200]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("staging-comparison response must be an object")
    return normalize_loosefruit_staging_payload(payload, url)
