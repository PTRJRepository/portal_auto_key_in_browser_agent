from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    config = json.loads((PROJECT_ROOT / "configs" / "app.json").read_text(encoding="utf-8"))
    base_url = str(config["api_base_url"]).rstrip("/")
    api_key = str(config["api_key"])
    divisions = ["ARA", "AB1", "AB2", "ARC"]
    month = 5
    year = 2026

    for division in divisions:
        params = {
            "period_month": month,
            "period_year": year,
            "division_code": division,
            "adjustment_type": "POTONGAN_KOTOR",
            "adjustment_name": "KOREKSI PANEN",
            "metadata_only": "false",
        }
        response = requests.get(
            f"{base_url}/payroll/manual-adjustment/by-api-key?{urlencode(params)}",
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        needed = [row for row in rows if input_needed(row)]
        missing = [row for row in rows if sync_status(row) in {"MISS", "MISSING", "NOT_FOUND"}]
        mismatch = [row for row in rows if match_status(row) in {"MISMATCH", "DIFF", "PARTIAL"} or sync_status(row) in {"DIFF", "PARTIAL"}]
        by_name = Counter(text(row, "adjustment_name").upper() for row in needed)
        totals = defaultdict(float)
        for row in needed:
            totals[text(row, "adjustment_name").upper()] += float(row.get("amount") or 0)

        print(f"{division}: fetched={len(rows)} needed={len(needed)} miss={len(missing)} mismatch={len(mismatch)}")
        for name, count in by_name.most_common():
            print(f"  {name}: count={count} amount={totals[name]:.0f}")
        for row in needed[:20]:
            print(
                "  sample "
                f"id={row.get('id')} emp={text(row, 'emp_code')} gang={text(row, 'gang_code')} "
                f"amount={float(row.get('amount') or 0):.0f} sync={sync_status(row)} match={match_status(row)} "
                f"detail={detail_label(row)}"
            )


def text(row: dict, *keys: str) -> str:
    return " ".join(str(row.get(key) or "") for key in keys).strip()


def remarks_token(row: dict, key: str) -> str:
    prefix = f"{key.lower()}:"
    for part in str(row.get("remarks") or "").split("|"):
        part = part.strip()
        if part.lower().startswith(prefix):
            return part.split(":", 1)[1].strip().upper()
    return ""


def sync_status(row: dict) -> str:
    return remarks_token(row, "sync")


def match_status(row: dict) -> str:
    return remarks_token(row, "match") or sync_status(row)


def input_needed(row: dict) -> bool:
    return sync_status(row) in {"MISS", "MISSING", "NOT_FOUND", "DIFF", "PARTIAL"} or match_status(row) in {"MISMATCH", "DIFF", "PARTIAL"}


def detail_label(row: dict) -> str:
    items = row.get("detail_items")
    if isinstance(items, list) and items:
        item = items[0] if isinstance(items[0], dict) else {}
        kind = str(item.get("detail_type") or item.get("input_type") or "-")
        value = str(item.get("subblok") or item.get("vehicle_code") or item.get("nomor_kendaraan") or "-")
        return f"{kind}:{value}"
    return "-:-"


if __name__ == "__main__":
    main()
