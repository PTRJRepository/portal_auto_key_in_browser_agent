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
    print("=== Running Detailed Live DB Comparison Test ===")
    config = load_app_config()
    print(f"Query Gateway URL: {config.query_gateway_base_url}")
    print(f"Extend DB Server: {config.extend_db_server}")
    print(f"Extend DB Database: {config.extend_db_database}")
    
    gw_config = QueryGatewayConfig(
        base_url=config.query_gateway_base_url,
        api_key=config.query_gateway_api_key,
        server=config.query_gateway_server,
        database=config.query_gateway_database,
    )
    query_gateway = PlantwareDbPtrjGateway(config=gw_config)

    builtin_service = BuiltInComparisonService(config, query_gateway, None)
    
    period_month = config.default_period_month
    period_year = config.default_period_year
    division = config.default_division_code
    filters = ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]
    
    print(f"\nComparing for Period: {period_month}/{period_year}, Division: {division}")
    print(f"Filters: {filters}")
    
    try:
        result = builtin_service.compare_adtrans(
            period_month=period_month,
            period_year=period_year,
            division_code=division,
            filters=filters
        )
        print(f"\n--- Built-in compare_adtrans ---")
        print(f"Result Success: {result.get('success')}")
        data = result.get("data", {})
        print(f"Total employees: {data.get('total_employees')}")
        print(f"Match count: {data.get('match_count')}")
        print(f"Mismatch count: {data.get('mismatch_count')}")
        print(f"Missing in adjustments: {data.get('missing_in_adjustments')}")
        print(f"Extra in db_ptrj: {data.get('extra_in_db_ptrj')}")
        
        comparisons = data.get("comparisons", [])
        print(f"Total comparisons list size: {len(comparisons)}")
        statuses = {}
        for c in comparisons:
            statuses[c['status']] = statuses.get(c['status'], 0) + 1
        print(f"Status breakdown: {statuses}")
        
        # Test reverse compare
        print(f"\n--- Built-in reverse_compare_adtrans ---")
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
        print(f"Mismatch count: {rev_data.get('mismatch_amount') or rev_data.get('mismatch_count')}")
        print(f"Extra in adjustments: {rev_data.get('extra_in_adjustments')}")
        
        rev_comparisons = rev_data.get("comparisons", [])
        print(f"Total reverse comparisons list size: {len(rev_comparisons)}")
        rev_statuses = {}
        for c in rev_comparisons:
            rev_statuses[c['status']] = rev_statuses.get(c['status'], 0) + 1
        print(f"Status breakdown: {rev_statuses}")
        
        # Display some missing/mismatch/extra examples from reverse compare
        non_match = [c for c in rev_comparisons if c['status'] != 'MATCH']
        if non_match:
            print(f"\nReverse Non-matching Comparisons (first 10 out of {len(non_match)}):")
            for c in non_match[:10]:
                print(f"  Emp: {c['emp_code']}, Cat: {c['category']}, AdjName: {c['adjustment_name']}, Source: {c['source_amount']}, Stored: {c['stored_amount']}, Status: {c['status']}, Remarks: {c['remarks']}")
            
    except Exception as e:
        print(f"\nCaught execution exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
