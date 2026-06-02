from __future__ import annotations

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.core.config import load_app_config
from app.core.query_gateway import PlantwareDbPtrjGateway, QueryGatewayConfig
from app.core.built_in_comparison import BuiltInComparisonService

def main():
    print("=== Testing AB2, Month 5, Premium Comparison ===")

    config = load_app_config()
    print(f"Query Gateway URL: {config.query_gateway_base_url}")

    gw_config = QueryGatewayConfig(
        base_url=config.query_gateway_base_url,
        api_key=config.query_gateway_api_key,
        server=config.query_gateway_server,
        database=config.query_gateway_database,
    )
    query_gateway = PlantwareDbPtrjGateway(config=gw_config)

    builtin_service = BuiltInComparisonService(config, query_gateway, None)

    # Test for AB2, Month 5, 2026
    period_month = 5
    period_year = 2026
    division = "AB2"
    filters = ["premi", "koreksi", "potongan"]

    print(f"\nComparing for Period: {period_month}/{period_year}, Division: {division}")
    print(f"Filters: {filters}")

    try:
        # Test reverse compare (extend_db vs db_ptrj)
        print(f"\n--- Built-in reverse_compare_adtrans (extend_db -> db_ptrj) ---")
        rev_result = builtin_service.reverse_compare_adtrans(
            period_month=period_month,
            period_year=period_year,
            division_code=division,
            filters=filters
        )
        print(f"Result Success: {rev_result.get('success')}")
        rev_data = rev_result.get("data", {})
        print(f"Total adjustments: {rev_data.get('total_adjustments')}")
        print(f"Match count: {rev_data.get('match_count')}")
        print(f"Mismatch count: {rev_data.get('mismatch_count')}")
        print(f"Extra in adjustments: {rev_data.get('extra_in_adjustments')}")

        rev_comparisons = rev_data.get("comparisons", [])
        print(f"Total reverse comparisons list size: {len(rev_comparisons)}")

        # Breakdown by status
        statuses = {}
        for c in rev_comparisons:
            s = c['status']
            statuses[s] = statuses.get(s, 0) + 1
        print(f"Status breakdown: {statuses}")

        # Show MISMATCH examples
        mismatches = [c for c in rev_comparisons if c['status'] == 'MISMATCH']
        print(f"\n=== MISMATCH Examples (first 10 of {len(mismatches)}) ===")
        for c in mismatches[:10]:
            ref = c.get('stored_amount', 0)
            src = c.get('source_amount', 0)
            diff = src - ref
            metadata = c.get('metadata_json', 'N/A')
            print(f"  Emp: {c['emp_code']}, Adj: {c['adjustment_name']}")
            print(f"    Ref (extend_db): {ref:,.0f}, Src (db_ptrj): {src:,.0f}, Diff: {diff:+,.0f}")
            print(f"    Metadata: {metadata[:100] if metadata and len(metadata) > 100 else metadata}")
            print()

        # Show MISSING examples
        missing = [c for c in rev_comparisons if c['status'] == 'MISSING']
        print(f"\n=== MISSING Examples (first 5 of {len(missing)}) ===")
        for c in missing[:5]:
            print(f"  Emp: {c['emp_code']}, Adj: {c['adjustment_name']}, Ref: {c.get('stored_amount', 0):,.0f}")

        # Show EXTRA examples
        extras = [c for c in rev_comparisons if c['status'] == 'EXTRA_IN_ADJUSTMENTS']
        print(f"\n=== EXTRA_IN_ADJUSTMENTS Examples (first 5 of {len(extras)}) ===")
        for c in extras[:5]:
            print(f"  Emp: {c['emp_code']}, Adj: {c['adjustment_name']}, Stored: {c.get('stored_amount', 0):,.0f}")

    except Exception as e:
        print(f"\nCaught execution exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()