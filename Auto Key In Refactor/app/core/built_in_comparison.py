from __future__ import annotations

import re
from typing import Any, Mapping

from app.core.config import AppConfig, load_divisions
from app.core.query_gateway import PlantwareDbPtrjGateway
from app.core.auto_buffer_models import normalize_auto_buffer_adjustment_name

FILTER_TO_ADJUSTMENT_NAME = {
    "spsi": "SPSI",
    "masa kerja": "MASA KERJA",
    "jabatan": "TUNJANGAN JABATAN",
    "pph": "POTONGAN PPH",
    "koreksi": "KOREKSI",
    "potongan": "POTONGAN",
    "potongan_upah_kotor": "POTONGAN KOTOR",
    "potongan_upah_bersih": "POTONGAN BERSIH",
    "premi": "PREMI",
    "premi_tunjangan": "PREMI TUNJANGAN",
    "brondol": "BRONDOL",
}

ADJUSTMENT_NAME_TO_FILTER = {
    name: filter_key for filter_key, name in FILTER_TO_ADJUSTMENT_NAME.items()
}

ADTRANS_DYNAMIC_PREMI_PATTERNS = ["%PREMI%", "%INSENTIF%", "%PANEN%", "%KINERJA%", "%RAWAT%", "%PRUN%"]

def normalize_upper(value: str) -> str:
    return str(value or "").strip().upper()

def normalize_adtrans_filter(filter_str: str) -> str:
    filter_key = str(filter_str or "").lower().strip()
    if "spsi" in filter_key:
        return "spsi"
    if "pph" in filter_key or "pajak" in filter_key:
        return "pph"
    if "masa" in filter_key:
        return "masa kerja"
    if "jabatan" in filter_key:
        return "jabatan"
    if "brondol" in filter_key:
        return "brondol"
    if "koreksi" in filter_key:
        return "koreksi"
    if "premi" in filter_key:
        return "premi"
    if "potongan" in filter_key:
        return "potongan"
    return filter_key

def is_brondol_doc_desc(doc_desc: str) -> bool:
    upper = normalize_upper(doc_desc)
    if "BRONDOL" not in upper:
        return False
    return not bool(re.search(r'\bBANTU\b', upper))

def is_dynamic_premi_doc_desc(doc_desc: str) -> bool:
    upper = normalize_upper(doc_desc)
    if not upper or is_brondol_doc_desc(upper):
        return False
    keywords_exclude = ["PPH", "JABATAN", "BERAS", "LEMBUR", "MASA", "POTONGAN", "KOREKSI", "SPSI"]
    if any(k in upper for k in keywords_exclude):
        return False
    keywords_include = ["PREMI", "INSENTIF", "PANEN", "KINERJA", "RAWAT", "PRUN"]
    return any(k in upper for k in keywords_include)

def is_dynamic_potongan_doc_desc(doc_desc: str) -> bool:
    upper = normalize_upper(doc_desc)
    if not upper:
        return False
    if "KOREKSI" in upper:
        return True
    if "SPSI" in upper or "PPH" in upper:
        return False
    return upper.startswith("POTONGAN") or upper.startswith("POT ") or upper.startswith("POT_")

def build_adtrans_doc_desc_sql_patterns(filter_str: str) -> list[str]:
    category = normalize_adtrans_filter(filter_str)
    if category == "spsi":
        return ["%SPSI%"]
    if category == "pph":
        return ["%PPH%", "%PAJAK%"]
    if category == "masa kerja":
        return ["%MASA%KERJA%"]
    if category == "jabatan":
        return ["%JABATAN%"]
    if category == "brondol":
        return ["%BRONDOL%"]
    if category == "koreksi":
        return ["%KOREKSI%"]
    if category == "premi":
        return ADTRANS_DYNAMIC_PREMI_PATTERNS
    if category == "potongan":
        return ["POT%", "POTONGAN%"]
    return [f"%{category.upper()}%"]

def build_adtrans_doc_desc_sql_condition(column_name: str, filter_str: str) -> str:
    category = normalize_adtrans_filter(filter_str)
    if category == "pph":
        return f"((UPPER({column_name}) LIKE '%PPH%' OR UPPER({column_name}) LIKE '%PAJAK%') AND UPPER({column_name}) NOT LIKE '%PREMI%')"
    
    patterns = build_adtrans_doc_desc_sql_patterns(filter_str)
    conditions = []
    for pattern in patterns:
        escaped_pattern = pattern.replace("'", "''")
        conditions.append(f"UPPER({column_name}) LIKE '{escaped_pattern}'")
    return " OR ".join(conditions)

def matches_adtrans_doc_desc_filter(doc_desc: str, filter_str: str) -> bool:
    category = normalize_adtrans_filter(filter_str)
    upper = normalize_upper(doc_desc)
    
    if category == "spsi":
        return "SPSI" in upper
    if category == "pph":
        return ("PPH" in upper or "PAJAK" in upper) and "PREMI" not in upper
    if category == "masa kerja":
        return "MASA" in upper and "KERJA" in upper
    if category == "jabatan":
        return "JABATAN" in upper
    if category == "brondol":
        return is_brondol_doc_desc(upper)
    if category == "koreksi":
        return "KOREKSI" in upper
    if category == "premi":
        return is_dynamic_premi_doc_desc(upper)
    if category == "potongan":
        return "KOREKSI" not in upper and is_dynamic_potongan_doc_desc(upper)
    return category.upper() in upper


class BuiltInComparisonService:
    def __init__(self, config: AppConfig, query_gateway: PlantwareDbPtrjGateway, api_client: Any):
        self.config = config
        self.query_gateway = query_gateway
        self.api_client = api_client

    def compare_adtrans(
        self,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Built-in implementation of Daftar Upah's /compare-adtrans API.
        Compares PR_ADTRANS (db_ptrj) values with payroll_manual_adjustments (extend_db_ptrj).
        """
        filters = filters or []
        normalized_filters = [normalize_adtrans_filter(f) for f in filters if f.strip()]
        
        if not normalized_filters:
            return {
                "success": True,
                "data": {
                    "division": division_code,
                    "period_month": period_month,
                    "period_year": period_year,
                    "compared_categories": [],
                    "total_employees": 0,
                    "match_count": 0,
                    "mismatch_count": 0,
                    "missing_in_adjustments": 0,
                    "extra_in_db_ptrj": 0,
                    "comparisons": []
                }
            }

        # 1. Resolve division options and physical location code
        divisions = load_divisions()
        division_opt = next((d for d in divisions if d.code.upper() == division_code.strip().upper()), None)
        
        if division_opt:
            normalized_division_code = division_opt.effective_location_code
            is_virtual = division_opt.virtual
            virtual_gang_codes = [division_opt.code.upper()] + [a.upper() for a in division_opt.aliases]
        else:
            normalized_division_code = division_code.strip().upper()
            is_virtual = False
            virtual_gang_codes = []

        loc_code_map = {
            "PG1A": "P1A", "PG1B": "P1B", "PG2A": "P2A", "PG2B": "P2B",
            "ARB1": "AB1", "ARB2": "AB2", "AREC": "ARC",
            "PLASMA1A": "P1A", "PLASMA1B": "P1B", "PLASMA2A": "P2A", "PLASMA2B": "P2B",
            "1A": "P1A", "1B": "P1B", "2A": "P2A", "2B": "P2B"
        }
        normalized_division_code = loc_code_map.get(normalized_division_code, normalized_division_code)

        # 2. Get PR_ADTRANS totals per employee per category from db_ptrj
        case_statements = ", ".join([
            f"SUM(CASE WHEN {build_adtrans_doc_desc_sql_condition('DocDesc', f)} THEN Amount ELSE 0 END) as [{f}]"
            for f in normalized_filters
        ])

        if is_virtual and virtual_gang_codes:
            gang_join = "JOIN HR_GANGLN gl ON RTRIM(gl.GangMember) = RTRIM(t.EmpCode)"
            gang_placeholders = ", ".join([f"@gang{idx}" for idx in range(len(virtual_gang_codes))])
            gang_where = f"AND UPPER(RTRIM(gl.GangCode)) IN ({gang_placeholders})"
        else:
            gang_join = ""
            gang_where = ""

        adtrans_query = f"""
            SELECT
                emp_code,
                MAX(nik) as nik,
                {case_statements}
            FROM (
                SELECT
                    RTRIM(t.EmpCode) as emp_code,
                    RTRIM(ISNULL(e.NewICNo, '')) as nik,
                    t.DocDesc,
                    ln.Amount
                FROM PR_ADTRANS t
                {gang_join}
                LEFT JOIN HR_EMPLOYEE e ON RTRIM(e.EmpCode) = RTRIM(t.EmpCode)
                JOIN PR_ADTRANSLN ln ON t.ID = ln.MasterID
                WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                  AND t.PhyMonth = @phyMonth
                  AND t.PhyYear = @phyYear
                  {gang_where}

                UNION ALL

                SELECT
                    RTRIM(t.EmpCode) as emp_code,
                    RTRIM(ISNULL(e.NewICNo, '')) as nik,
                    t.DocDesc,
                    ln.Amount
                FROM PR_ADTRANS_ARC t
                {gang_join}
                LEFT JOIN HR_EMPLOYEE e ON RTRIM(e.EmpCode) = RTRIM(t.EmpCode)
                JOIN PR_ADTRANSLN_ARC ln ON t.ID = ln.MasterID
                WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                  AND t.PhyMonth = @phyMonth
                  AND t.PhyYear = @phyYear
                  {gang_where}
            ) src
            GROUP BY emp_code
        """

        # Build named parameters
        params = {
            "locCode": normalized_division_code,
            "phyMonth": period_month,
            "phyYear": period_year
        }
        if is_virtual and virtual_gang_codes:
            for idx, g in enumerate(virtual_gang_codes):
                params[f"gang{idx}"] = g

        adtrans_res = self.query_gateway.execute(
            sql=adtrans_query,
            params=params,
            server=self.config.query_gateway_server,
            database=self.config.query_gateway_database,
        )
        adtrans_rows = adtrans_res.recordset

        # 3. Get detailed document details for comparisons
        detail_query = f"""
            SELECT
                RTRIM(t.EmpCode) as emp_code,
                RTRIM(t.DocID) as doc_id,
                RTRIM(t.DocDesc) as doc_desc,
                ln.Amount as amount
            FROM PR_ADTRANS t
            {gang_join}
            JOIN PR_ADTRANSLN ln ON t.ID = ln.MasterID
            WHERE UPPER(RTRIM(t.LocCode)) = @locCode
              AND t.PhyMonth = @phyMonth
              AND t.PhyYear = @phyYear
              {gang_where}

            UNION ALL

            SELECT
                RTRIM(t.EmpCode) as emp_code,
                RTRIM(t.DocID) as doc_id,
                RTRIM(t.DocDesc) as doc_desc,
                ln.Amount as amount
            FROM PR_ADTRANS_ARC t
            {gang_join}
            JOIN PR_ADTRANSLN_ARC ln ON t.ID = ln.MasterID
            WHERE UPPER(RTRIM(t.LocCode)) = @locCode
              AND t.PhyMonth = @phyMonth
              AND t.PhyYear = @phyYear
              {gang_where}
        """

        detail_res = self.query_gateway.execute(
            sql=detail_query,
            params=params,
            server=self.config.query_gateway_server,
            database=self.config.query_gateway_database,
        )
        detail_rows = detail_res.recordset

        doc_details_map = {}
        for row in detail_rows:
            emp_code = str(row.get("emp_code") or "").strip().upper()
            doc_desc = str(row.get("doc_desc") or "").strip()
            doc_id = str(row.get("doc_id") or "").strip() if row.get("doc_id") else None
            amount = float(row.get("amount") or 0.0)
            
            for f in normalized_filters:
                if not matches_adtrans_doc_desc_filter(doc_desc, f):
                    continue
                key = f"{emp_code}|{f}"
                if key not in doc_details_map:
                    doc_details_map[key] = []
                doc_details_map[key].append({
                    "doc_desc": doc_desc,
                    "doc_id": doc_id,
                    "amount": amount
                })

        # 4. Get stored manual adjustments from extend_db_ptrj
        adjustment_division_codes = list(set([
            division_code.strip().upper(),
            normalized_division_code
        ]))
        placeholders = ", ".join([f"@div{idx}" for idx in range(len(adjustment_division_codes))])
        
        adjustments_sql = f"""
            SELECT emp_code, nik, adjustment_type, adjustment_name, amount, remarks, gang_code, division_code
            FROM dbo.payroll_manual_adjustments
            WHERE period_month = @periodMonth AND period_year = @periodYear
              AND UPPER(RTRIM(division_code)) IN ({placeholders})
        """
        
        adj_params = {
            "periodMonth": period_month,
            "periodYear": period_year
        }
        for idx, div in enumerate(adjustment_division_codes):
            adj_params[f"div{idx}"] = div
            
        adjustments_res = self.query_gateway.execute(
            sql=adjustments_sql,
            params=adj_params,
            server=self.config.extend_db_server,
            database=self.config.extend_db_database,
        )
        adjustment_rows = adjustments_res.recordset

        # 5. Build map of stored adjustments: identity -> category -> item
        category_to_adjustment_name = {
            "spsi": "SPSI",
            "masa kerja": "MASA KERJA",
            "jabatan": "TUNJANGAN JABATAN"
        }
        auto_buffer_comparable_names = set(category_to_adjustment_name.values())
        
        stored_map = {}
        for row in adjustment_rows:
            emp_code = str(row.get("emp_code") or "").strip().upper()
            nik = str(row.get("nik") or "").strip().upper()
            adj_type = str(row.get("adjustment_type") or "").strip().upper()
            adj_name = str(row.get("adjustment_name") or "").strip().upper()
            
            norm_name = normalize_auto_buffer_adjustment_name(adj_name)
            comparable_adj_name = norm_name if norm_name in auto_buffer_comparable_names else adj_name
            
            category = None
            for cat, name in category_to_adjustment_name.items():
                if name == comparable_adj_name:
                    category = cat
                    break
                    
            if not category and adj_type == "PREMI":
                category = "premi"
            if not category and adj_type == "POTONGAN_KOTOR":
                category = "koreksi" if "KOREKSI" in adj_name else "potongan"
                
            if not category or category not in normalized_filters:
                continue
                
            stored_item = {
                "amount": float(row.get("amount") or 0.0),
                "remarks": str(row.get("remarks") or ""),
                "gang_code": str(row.get("gang_code") or ""),
                "adjustment_name": comparable_adj_name if comparable_adj_name in auto_buffer_comparable_names else adj_name
            }
            
            identity_keys = {emp_code, nik} - {""}
            for key in identity_keys:
                if key not in stored_map:
                    stored_map[key] = {}
                stored_map[key][category] = stored_item

        # 6. Compare each employee's ADTRANS values with stored adjustments
        comparisons = []
        match_count = mismatch_count = missing_count = extra_in_db_ptrj_count = 0
        
        for row in adtrans_rows:
            emp_code = str(row.get("emp_code") or "").strip().upper()
            source_nik = str(row.get("nik") or "").strip().upper()
            
            emp_stored = stored_map.get(emp_code) or (stored_map.get(source_nik) if source_nik else None)
            
            for f in normalized_filters:
                source_amount = float(row.get(f) or 0.0)
                stored = emp_stored.get(f) if emp_stored else None
                
                # Skip if source amount is 0 and no stored adjustment exists
                if abs(source_amount) <= 0.01 and not stored:
                    continue
                    
                stored_amount = float(stored["amount"]) if stored else None
                is_missing = stored is None
                
                if is_missing:
                    status = "MISSING"
                    missing_count += 1
                else:
                    is_match = abs(source_amount - stored_amount) <= 0.01
                    if is_match:
                        status = "MATCH"
                        match_count += 1
                    else:
                        status = "MISMATCH"
                        mismatch_count += 1
                        
                if abs(source_amount) > 0.01 and status != "MATCH":
                    extra_in_db_ptrj_count += 1
                    
                adjustment_name = stored["adjustment_name"] if stored else (category_to_adjustment_name.get(f) or f.upper())
                diff = source_amount - stored_amount if stored_amount is not None else None
                
                comparisons.append({
                    "emp_code": emp_code,
                    "stored_emp_identifier": source_nik if source_nik and source_nik != emp_code else None,
                    "category": f,
                    "adjustment_name": adjustment_name,
                    "source_amount": source_amount,
                    "stored_amount": stored_amount,
                    "db_ptrj_amount": source_amount,
                    "extend_db_ptrj_amount": stored_amount,
                    "diff": diff,
                    "status": status,
                    "db_ptrj_doc_desc_details": doc_details_map.get(f"{emp_code}|{f}", []),
                    "extend_db_ptrj_remarks": stored["remarks"] if stored else None,
                    "gang_code": stored["gang_code"] if stored else None,
                    "remarks": stored["remarks"] if stored else None
                })

        return {
            "success": True,
            "data": {
                "division": division_code,
                "period_month": period_month,
                "period_year": period_year,
                "compared_categories": normalized_filters,
                "total_employees": len(adtrans_rows),
                "match_count": match_count,
                "mismatch_count": mismatch_count,
                "missing_in_adjustments": missing_count,
                "extra_in_db_ptrj": extra_in_db_ptrj_count,
                "comparisons": comparisons
            }
        }

    def reverse_compare_adtrans(
        self,
        period_month: int,
        period_year: int,
        division_code: str,
        filters: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Built-in implementation of Daftar Upah's /reverse-compare-adtrans API.
        Queries extend_db_ptrj directly and compares with db_ptrj totals.
        """
        filters = filters or []
        normalized_filters = [normalize_adtrans_filter(f) for f in filters if f.strip()]
        
        # 1. Fetch extend_db adjustments
        extend_db_rows = self._fetch_extend_db_adjustments(period_month, period_year, division_code, normalized_filters)
        
        # 2. Get list of distinct employee codes/identifiers from adjustments
        emp_identifiers = set()
        for row in extend_db_rows:
            emp_code = str(row.get("emp_code") or "").strip().upper()
            nik = str(row.get("nik") or "").strip().upper()
            if emp_code:
                emp_identifiers.add(emp_code)
            if nik:
                emp_identifiers.add(nik)

        # 3. Fetch all totals and details from PR_ADTRANS/PR_ADTRANS_ARC using division parameters
        divisions = load_divisions()
        division_opt = next((d for d in divisions if d.code.upper() == division_code.strip().upper()), None)
        
        if division_opt:
            normalized_division_code = division_opt.effective_location_code
            is_virtual = division_opt.virtual
            virtual_gang_codes = [division_opt.code.upper()] + [a.upper() for a in division_opt.aliases]
        else:
            normalized_division_code = division_code.strip().upper()
            is_virtual = False
            virtual_gang_codes = []

        loc_code_map = {
            "PG1A": "P1A", "PG1B": "P1B", "PG2A": "P2A", "PG2B": "P2B",
            "ARB1": "AB1", "ARB2": "AB2", "AREC": "ARC",
            "PLASMA1A": "P1A", "PLASMA1B": "P1B", "PLASMA2A": "P2A", "PLASMA2B": "P2B",
            "1A": "P1A", "1B": "P1B", "2A": "P2A", "2B": "P2B"
        }
        normalized_division_code = loc_code_map.get(normalized_division_code, normalized_division_code)

        case_statements = ", ".join([
            f"SUM(CASE WHEN {build_adtrans_doc_desc_sql_condition('DocDesc', f)} THEN Amount ELSE 0 END) as [{f}]"
            for f in normalized_filters
        ])

        if is_virtual and virtual_gang_codes:
            gang_join = "JOIN HR_GANGLN gl ON RTRIM(gl.GangMember) = RTRIM(t.EmpCode)"
            gang_placeholders = ", ".join([f"@gang{idx}" for idx in range(len(virtual_gang_codes))])
            gang_where = f"AND UPPER(RTRIM(gl.GangCode)) IN ({gang_placeholders})"
        else:
            gang_join = ""
            gang_where = ""

        source_map = {}
        doc_details_map = {}

        if normalized_filters:
            adtrans_query = f"""
                SELECT
                    emp_code,
                    MAX(nik) as nik,
                    {case_statements}
                FROM (
                    SELECT
                        RTRIM(t.EmpCode) as emp_code,
                        RTRIM(ISNULL(e.NewICNo, '')) as nik,
                        t.DocDesc,
                        ln.Amount
                    FROM PR_ADTRANS t
                    {gang_join}
                    LEFT JOIN HR_EMPLOYEE e ON RTRIM(e.EmpCode) = RTRIM(t.EmpCode)
                    JOIN PR_ADTRANSLN ln ON t.ID = ln.MasterID
                    WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                      AND t.PhyMonth = @phyMonth
                      AND t.PhyYear = @phyYear
                      {gang_where}

                    UNION ALL

                    SELECT
                        RTRIM(t.EmpCode) as emp_code,
                        RTRIM(ISNULL(e.NewICNo, '')) as nik,
                        t.DocDesc,
                        ln.Amount
                    FROM PR_ADTRANS_ARC t
                    {gang_join}
                    LEFT JOIN HR_EMPLOYEE e ON RTRIM(e.EmpCode) = RTRIM(t.EmpCode)
                    JOIN PR_ADTRANSLN_ARC ln ON t.ID = ln.MasterID
                    WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                      AND t.PhyMonth = @phyMonth
                      AND t.PhyYear = @phyYear
                      {gang_where}
                ) src
                GROUP BY emp_code
            """

            params = {
                "locCode": normalized_division_code,
                "phyMonth": period_month,
                "phyYear": period_year
            }
            if is_virtual and virtual_gang_codes:
                for idx, g in enumerate(virtual_gang_codes):
                    params[f"gang{idx}"] = g

            try:
                adtrans_res = self.query_gateway.execute(
                    sql=adtrans_query,
                    params=params,
                    server=self.config.query_gateway_server,
                    database=self.config.query_gateway_database,
                )
                for t in adtrans_res.recordset:
                    emp = str(t.get("emp_code") or "").strip().upper()
                    nik = str(t.get("nik") or "").strip().upper()
                    source_map[emp] = t
                    if nik:
                        source_map[nik] = t
                
                # Fetch details
                detail_query = f"""
                    SELECT
                        RTRIM(t.EmpCode) as emp_code,
                        RTRIM(t.DocID) as doc_id,
                        RTRIM(t.DocDesc) as doc_desc,
                        ln.Amount as amount
                    FROM PR_ADTRANS t
                    {gang_join}
                    JOIN PR_ADTRANSLN ln ON t.ID = ln.MasterID
                    WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                      AND t.PhyMonth = @phyMonth
                      AND t.PhyYear = @phyYear
                      {gang_where}

                    UNION ALL

                    SELECT
                        RTRIM(t.EmpCode) as emp_code,
                        RTRIM(t.DocID) as doc_id,
                        RTRIM(t.DocDesc) as doc_desc,
                        ln.Amount as amount
                    FROM PR_ADTRANS_ARC t
                    {gang_join}
                    JOIN PR_ADTRANSLN_ARC ln ON t.ID = ln.MasterID
                    WHERE UPPER(RTRIM(t.LocCode)) = @locCode
                      AND t.PhyMonth = @phyMonth
                      AND t.PhyYear = @phyYear
                      {gang_where}
                """
                detail_res = self.query_gateway.execute(
                    sql=detail_query,
                    params=params,
                    server=self.config.query_gateway_server,
                    database=self.config.query_gateway_database,
                )
                for row in detail_res.recordset:
                    emp_code = str(row.get("emp_code") or "").strip().upper()
                    doc_desc = str(row.get("doc_desc") or "").strip()
                    doc_id = str(row.get("doc_id") or "").strip() if row.get("doc_id") else None
                    amount = float(row.get("amount") or 0.0)
                    
                    for f in normalized_filters:
                        if not matches_adtrans_doc_desc_filter(doc_desc, f):
                            continue
                        key = f"{emp_code}|{f}"
                        if key not in doc_details_map:
                            doc_details_map[key] = []
                        doc_details_map[key].append({
                            "doc_desc": doc_desc,
                            "doc_id": doc_id,
                            "amount": amount
                        })
            except Exception as e:
                print(f"Direct DB fetch in reverse_compare failed, falling back to API: {e}")
                # Fallback to API check_adtrans_report
                adtrans_report = self.api_client.check_adtrans_report(
                    period_month=period_month,
                    period_year=period_year,
                    division_code=division_code,
                    filters=normalized_filters,
                )
                data = adtrans_report.get("data", {})
                if not isinstance(data, dict):
                    data = adtrans_report if isinstance(adtrans_report, dict) else {}
                totals = data.get("totals", [])
                if not totals and "data" in data and isinstance(data["data"], dict):
                    totals = data["data"].get("totals", [])
                doc_details = data.get("doc_desc_details", [])
                
                for t in totals:
                    if not isinstance(t, dict): continue
                    emp = str(t.get("emp_code", "")).strip().upper()
                    source_map[emp] = t

                for d in doc_details:
                    if not isinstance(d, dict): continue
                    emp = str(d.get("emp_code", "")).strip().upper()
                    cat = str(d.get("category", "")).strip().lower()
                    key = f"{emp}|{cat}"
                    if key not in doc_details_map:
                        doc_details_map[key] = []
                    doc_details_map[key].append({
                        "doc_desc": str(d.get("doc_desc", "")).strip(),
                        "doc_id": str(d.get("doc_id", "")).strip() if d.get("doc_id") else None,
                        "amount": float(d.get("amount") or 0.0),
                    })

        comparisons = []
        match_count = mismatch_count = extra_count = 0
        
        for row in extend_db_rows:
            emp_code = str(row.get("emp_code", "")).strip().upper()
            nik = str(row.get("nik", "")).strip().upper()
            adj_type = str(row.get("adjustment_type", "")).strip().upper()
            adj_name = str(row.get("adjustment_name", "")).strip().upper()

            # Try direct matching for KOREKSI PANEN first
            category = None
            if "KOREKSI" in adj_name:
                category = "koreksi"
            elif "PREMI" in adj_name and "TUNJANGAN" in adj_name:
                category = "premi_tunjangan"
            elif "PREMI" in adj_name:
                category = "premi"
            elif "POTONGAN" in adj_name and "BERSIH" in adj_name:
                category = "potongan_upah_bersih"
            elif "POTONGAN" in adj_name and ("KOTOR" in adj_name or "KOREKSI" in adj_name):
                category = "potongan_upah_kotor"
            elif "BRONDOL" in adj_name:
                category = "brondol"
            else:
                # Try normalization for other types
                norm_name = normalize_auto_buffer_adjustment_name(adj_name)
                category = ADJUSTMENT_NAME_TO_FILTER.get(norm_name)
                if not category and adj_type == "PREMI":
                    category = "premi"
                if not category and adj_type == "POTONGAN_KOTOR":
                    category = "potongan_upah_kotor"

            if not category or category not in normalized_filters:
                continue
                
            stored_amount = float(row.get("amount") or 0.0)
            
            source_row = source_map.get(emp_code) or (source_map.get(nik) if nik else {})
            source_amount = float(source_row.get(category) or 0.0)
            
            diff = source_amount - stored_amount
            is_match = abs(diff) <= 0.01
            
            if is_match:
                status = "MATCH"
                match_count += 1
            elif source_amount == 0 and stored_amount != 0:
                status = "EXTRA_IN_ADJUSTMENTS"
                extra_count += 1
            else:
                status = "MISMATCH"
                mismatch_count += 1
                
            comparisons.append({
                "emp_code": emp_code,
                "stored_emp_identifier": emp_code,
                "category": category,
                "adjustment_name": adj_name,
                "stored_amount": stored_amount,
                "source_amount": source_amount,
                "db_ptrj_amount": source_amount,
                "extend_db_ptrj_amount": stored_amount,
                "diff": diff,
                "status": status,
                "db_ptrj_doc_desc_details": doc_details_map.get(f"{emp_code}|{category}", []),
                "extend_db_ptrj_remarks": row.get("remarks"),
                "gang_code": row.get("gang_code"),
                "division_code": row.get("division_code"),
                "remarks": row.get("remarks"),
                # Include metadata for sub-blok details
                "metadata_json": row.get("metadata_json"),
            })
            
        return {
            "success": True,
            "data": {
                "division": division_code,
                "period_month": period_month,
                "period_year": period_year,
                "compared_categories": normalized_filters,
                "total_adjustments": len(comparisons),
                "match_count": match_count,
                "mismatch_count": mismatch_count,
                "extra_in_adjustments": extra_count,
                "comparisons": comparisons
            }
        }
        
    def _fetch_extend_db_adjustments(self, period_month: int, period_year: int, division_code: str, filters: list[str]) -> list[dict[str, Any]]:
        adjustment_names = []
        includes_manual = False
        
        for f in filters:
            f = f.strip().lower()
            if f in FILTER_TO_ADJUSTMENT_NAME:
                name = FILTER_TO_ADJUSTMENT_NAME[f]
                adjustment_names.append(name)
                adjustment_names.append(f"AUTO {name}")
            if f in ("premi", "koreksi", "potongan", "potongan_upah_bersih", "potongan upah bersih", "tunjangan premi"):
                includes_manual = True
                
        # Resolve virtual division division codes for extend_db lookup
        divisions = load_divisions()
        division_opt = next((d for d in divisions if d.code.upper() == division_code.strip().upper()), None)
        if division_opt:
            adjustment_division_codes = list(set([
                division_code.strip().upper(),
                division_opt.effective_location_code
            ]))
        else:
            adjustment_division_codes = [division_code.strip().upper()]

        placeholders = ", ".join([f"@div{idx}" for idx in range(len(adjustment_division_codes))])
        sql = f"""
            SELECT emp_code, nik, adjustment_type, adjustment_name, amount, remarks, gang_code, division_code, metadata_json
            FROM dbo.payroll_manual_adjustments
            WHERE period_month = @periodMonth AND period_year = @periodYear
              AND UPPER(RTRIM(division_code)) IN ({placeholders})
        """
        
        conds = []
        if adjustment_names:
            names_in = ", ".join([f"'{n}'" for n in adjustment_names])
            conds.append(f"(adjustment_type = 'AUTO_BUFFER' AND UPPER(RTRIM(adjustment_name)) IN ({names_in}))")
            
        if includes_manual:
            conds.append("adjustment_type IN ('PREMI', 'POTONGAN_KOTOR', 'POTONGAN_BERSIH')")
            
        if conds:
            sql += " AND (" + " OR ".join(conds) + ")"
            
        params = {
            "periodMonth": period_month,
            "periodYear": period_year
        }
        for idx, div in enumerate(adjustment_division_codes):
            params[f"div{idx}"] = div

        result = self.query_gateway.execute(
            sql=sql,
            params=params,
            server=self.config.extend_db_server,
            database=self.config.extend_db_database,
        )
        return result.recordset
