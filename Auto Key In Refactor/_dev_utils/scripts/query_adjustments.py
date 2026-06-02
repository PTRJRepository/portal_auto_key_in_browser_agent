from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.core.config import load_app_config
from app.core.query_gateway import PlantwareDbPtrjGateway, QueryGatewayConfig

def main():
    print("=== Querying manual adjustments from extend_db ===")
    config = load_app_config()
    
    gw_config = QueryGatewayConfig(
        base_url=config.query_gateway_base_url,
        api_key=config.query_gateway_api_key,
        server=config.query_gateway_server,
        database=config.query_gateway_database,
    )
    query_gateway = PlantwareDbPtrjGateway(config=gw_config)

    # Let's count distinct adjustment_type and adjustment_name
    summary_sql = """
        SELECT adjustment_type, adjustment_name, COUNT(*) as count
        FROM dbo.payroll_manual_adjustments
        WHERE period_month = 4 AND period_year = 2026
          AND division_code = 'AB1'
        GROUP BY adjustment_type, adjustment_name
        ORDER BY adjustment_type, adjustment_name
    """
    
    try:
        res = query_gateway.execute(
            sql=summary_sql,
            params={},
            server=config.extend_db_server,
            database=config.extend_db_database
        )
        print("\nDistinct Adjustment Types and Names in extend_db:")
        for r in res.recordset:
            print(f"  Type: {r['adjustment_type']}, Name: {r['adjustment_name']}, Count: {r['count']}")
            
        # Let's inspect a few AUTO_BUFFER rows specifically
        auto_sql = """
            SELECT TOP 10 emp_code, nik, adjustment_type, adjustment_name, amount, remarks, division_code
            FROM dbo.payroll_manual_adjustments
            WHERE period_month = 4 AND period_year = 2026
              AND division_code = 'AB1'
              AND adjustment_type = 'AUTO_BUFFER'
        """
        res_auto = query_gateway.execute(
            sql=auto_sql,
            params={},
            server=config.extend_db_server,
            database=config.extend_db_database
        )
        print("\nSample AUTO_BUFFER records:")
        for r in res_auto.recordset:
            print(f"  Emp: {r['emp_code']}, NIK: {r['nik']}, Type: {r['adjustment_type']}, Name: {r['adjustment_name']}, Amount: {r['amount']}, Remarks: {r['remarks']}")

    except Exception as e:
        print(f"Failed to query database: {e}")

if __name__ == "__main__":
    main()
