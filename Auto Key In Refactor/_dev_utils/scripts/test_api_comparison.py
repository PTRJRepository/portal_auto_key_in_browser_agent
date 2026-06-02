from __future__ import annotations

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.core.config import load_app_config
from app.core.api_client import ManualAdjustmentApiClient
from app.core.category_registry import load_category_registry

def main():
    print("=== Running Live API Comparison Test ===")
    config = load_app_config()
    print(f"API Base URL: {config.api_base_url}")
    print(f"API Key: {config.api_key[:8]}... (truncated)")

    categories = load_category_registry()
    client = ManualAdjustmentApiClient(
        base_url=config.api_base_url,
        api_key=config.api_key,
        categories=categories
    )

    period_month = config.default_period_month
    period_year = config.default_period_year
    division = config.default_division_code
    filters = ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]

    # In division_monitor, P1B becomes PG1B, etc.
    from app.ui.division_monitor import DIVISION_TO_COMPARE_CODE
    compare_division_code = DIVISION_TO_COMPARE_CODE.get(division, division)

    print(f"\nComparing via API for Period: {period_month}/{period_year}, Division: {compare_division_code}")
    print(f"Filters: {filters}")

    try:
        print("\n--- Testing compare_adtrans API ---")
        compare_res = client.compare_adtrans(
            period_month=period_month,
            period_year=period_year,
            division_code=compare_division_code,
            filters=filters
        )
        print(f"Success: {compare_res.get('success')}")
        data = compare_res.get("data", {})
        print(f"Total employees: {data.get('total_employees')}")
        print(f"Match count: {data.get('match_count')}")
        print(f"Mismatch count: {data.get('mismatch_count')}")
        print(f"Missing count: {data.get('missing_in_adjustments')}")
        
        comparisons = data.get("comparisons", [])
        print(f"Comparisons list size: {len(comparisons)}")
        statuses = {}
        for c in comparisons:
            statuses[c.get('status')] = statuses.get(c.get('status'), 0) + 1
        print(f"Status breakdown: {statuses}")
        
    except Exception as e:
        print(f"compare_adtrans API call failed: {e}")

    try:
        print("\n--- Testing reverse_compare_adtrans API ---")
        rev_res = client.reverse_compare_adtrans(
            period_month=period_month,
            period_year=period_year,
            division_code=compare_division_code,
            filters=filters
        )
        print(f"Success: {rev_res.get('success')}")
        data = rev_res.get("data", {})
        print(f"Total adjustments: {data.get('total_adjustments')}")
        print(f"Match count: {data.get('match_count')}")
        print(f"Mismatch count: {data.get('mismatch_count')}")
        print(f"Extra count: {data.get('extra_in_adjustments')}")
        
        comparisons = data.get("comparisons", [])
        print(f"Comparisons list size: {len(comparisons)}")
        statuses = {}
        for c in comparisons:
            statuses[c.get('status')] = statuses.get(c.get('status'), 0) + 1
        print(f"Status breakdown: {statuses}")
        
    except Exception as e:
        print(f"reverse_compare_adtrans API call failed: {e}")

if __name__ == "__main__":
    main()
