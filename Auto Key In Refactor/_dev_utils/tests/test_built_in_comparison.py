from __future__ import annotations

from unittest.mock import Mock
import pytest

from app.core.config import AppConfig, DivisionOption
from app.core.query_gateway import PlantwareDbPtrjGateway, QueryGatewayResult
from app.core.built_in_comparison import (
    BuiltInComparisonService,
    normalize_adtrans_filter,
    matches_adtrans_doc_desc_filter,
    is_brondol_doc_desc,
    is_dynamic_premi_doc_desc,
    is_dynamic_potongan_doc_desc,
)

def test_normalize_adtrans_filter():
    assert normalize_adtrans_filter("spsi") == "spsi"
    assert normalize_adtrans_filter("SPSI_POTONGAN") == "spsi"
    assert normalize_adtrans_filter("pajak pph21") == "pph"
    assert normalize_adtrans_filter("tunjangan masa kerja") == "masa kerja"
    assert normalize_adtrans_filter("tunjangan jabatan") == "jabatan"
    assert normalize_adtrans_filter("potongan panen") == "potongan"
    assert normalize_adtrans_filter("koreksi panen") == "koreksi"
    assert normalize_adtrans_filter("premi panen") == "premi"
    assert normalize_adtrans_filter("custom_filter") == "custom_filter"

def test_matches_adtrans_doc_desc_filter():
    # SPSI
    assert matches_adtrans_doc_desc_filter("POTONGAN SPSI", "spsi") is True
    assert matches_adtrans_doc_desc_filter("TUNJANGAN SPSI", "spsi") is True
    assert matches_adtrans_doc_desc_filter("PREMI HARVEST", "spsi") is False

    # PPH
    assert matches_adtrans_doc_desc_filter("PAJAK PPH21", "pph") is True
    assert matches_adtrans_doc_desc_filter("POTONGAN PPH", "pph") is True
    assert matches_adtrans_doc_desc_filter("PREMI PPH", "pph") is False # contains PREMI, should be False

    # Masa Kerja
    assert matches_adtrans_doc_desc_filter("TUNJANGAN MASA KERJA", "masa kerja") is True
    assert matches_adtrans_doc_desc_filter("MASA BAKTI", "masa kerja") is False

    # Jabatan
    assert matches_adtrans_doc_desc_filter("TUNJANGAN JABATAN", "jabatan") is True
    assert matches_adtrans_doc_desc_filter("JABATAN MANDOR", "jabatan") is True

    # Koreksi / Potongan
    assert matches_adtrans_doc_desc_filter("KOREKSI PANEN", "koreksi") is True
    assert matches_adtrans_doc_desc_filter("POTONGAN PANEN", "potongan") is True
    assert matches_adtrans_doc_desc_filter("KOREKSI PANEN", "potongan") is False # Koreksi is excluded from potongan

    # Premi
    assert matches_adtrans_doc_desc_filter("PREMI PANEN", "premi") is True
    assert matches_adtrans_doc_desc_filter("INSENTIF MANDOR", "premi") is True

def test_compare_adtrans_match_mismatch_missing():
    # Create configuration mock
    config = AppConfig(
        query_gateway_server="SERVER_PROFILE_2",
        query_gateway_database="db_ptrj",
        extend_db_server="SERVER_PROFILE_1",
        extend_db_database="extend_db_ptrj",
    )
    
    # Mock database results
    adtrans_recordset = [
        {"emp_code": "A0001", "nik": "123456789", "spsi": 4000.0, "jabatan": 100000.0},
        {"emp_code": "A0002", "nik": "987654321", "spsi": 4000.0, "jabatan": 0.0},
    ]
    detail_recordset = [
        {"emp_code": "A0001", "doc_id": "D001", "doc_desc": "POTONGAN SPSI", "amount": 4000.0},
        {"emp_code": "A0001", "doc_id": "D002", "doc_desc": "TUNJANGAN JABATAN", "amount": 100000.0},
        {"emp_code": "A0002", "doc_id": "D001", "doc_desc": "POTONGAN SPSI", "amount": 4000.0},
    ]
    adjustments_recordset = [
        # Employee 1: SPSI matches, Tunjangan Jabatan mismatches
        {"emp_code": "A0001", "nik": "123456789", "adjustment_type": "AUTO_BUFFER", "adjustment_name": "SPSI", "amount": 4000.0, "remarks": "ok", "gang_code": "G1", "division_code": "AB1"},
        {"emp_code": "A0001", "nik": "123456789", "adjustment_type": "AUTO_BUFFER", "adjustment_name": "TUNJANGAN JABATAN", "amount": 80000.0, "remarks": "diff", "gang_code": "G1", "division_code": "AB1"},
        # Employee 2: SPSI matches, Tunjangan Jabatan is missing (we don't seed it in adjustments, but it's 0.0 in source so it's skipped anyway)
    ]
    
    gateway = Mock(spec=PlantwareDbPtrjGateway)
    
    # We will return different recordsets based on the SQL query
    def mock_execute(sql, params, server, database):
        if "dbo.payroll_manual_adjustments" in sql:
            return QueryGatewayResult(server, database, adjustments_recordset, [len(adjustments_recordset)], 1.0, {})
        elif "SUM(CASE WHEN" in sql:
            return QueryGatewayResult(server, database, adtrans_recordset, [len(adtrans_recordset)], 1.0, {})
        else:
            return QueryGatewayResult(server, database, detail_recordset, [len(detail_recordset)], 1.0, {})
            
    gateway.execute.side_effect = mock_execute
    
    api_client = Mock()
    service = BuiltInComparisonService(config, gateway, api_client)
    
    result = service.compare_adtrans(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        filters=["spsi", "jabatan"]
    )
    
    assert result["success"] is True
    data = result["data"]
    assert data["division"] == "AB1"
    assert data["period_month"] == 4
    assert data["period_year"] == 2026
    
    comparisons = data["comparisons"]
    # Total comparisons should cover:
    # A0001: spsi (match) and jabatan (mismatch)
    # A0002: spsi (match) -> since jabatan is 0 and not in stored, it is skipped
    assert len(comparisons) == 3
    
    a1_spsi = next(c for c in comparisons if c["emp_code"] == "A0001" and c["category"] == "spsi")
    a1_jab = next(c for c in comparisons if c["emp_code"] == "A0001" and c["category"] == "jabatan")
    a2_spsi = next(c for c in comparisons if c["emp_code"] == "A0002" and c["category"] == "spsi")
    
    assert a1_spsi["status"] == "MATCH"
    assert a1_spsi["source_amount"] == 4000.0
    assert a1_spsi["stored_amount"] == 4000.0
    assert a1_spsi["diff"] == 0.0
    
    assert a1_jab["status"] == "MISMATCH"
    assert a1_jab["source_amount"] == 100000.0
    assert a1_jab["stored_amount"] == 80000.0
    assert a1_jab["diff"] == 20000.0
    
    assert a2_spsi["status"] == "MISSING" # Oh, wait, in our mock, A0002 has NO spsi in adjustments recordset! Let's check:
    # Yes, adjustments_recordset only has entries for A0001! So A0002 is indeed missing!
    assert a2_spsi["source_amount"] == 4000.0
    assert a2_spsi["stored_amount"] is None
