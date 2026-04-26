from app.core.category_registry import AdjustmentCategory, CategoryRegistry
from app.core.api_client import ManualAdjustmentQuery
from app.core.config import load_app_config
from app.core.models import normalize_record
from app.core.run_service import apply_row_limit, filter_by_category


def test_app_config_fallback_uses_api_division_alias(tmp_path):
    missing_config = tmp_path / "missing.json"
    config = load_app_config(missing_config)
    assert config.default_division_code == "P1B"


def test_manual_adjustment_query_omits_empty_optional_filters():
    query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="AB1", gang_code="")
    assert query.params() == {"period_month": "4", "period_year": "2026", "division_code": "AB1"}


def test_normalize_record_uppercases_codes_and_preserves_name():
    record = normalize_record({
        "id": "10",
        "period_month": "4",
        "period_year": 2026,
        "emp_code": " b0745 ",
        "gang_code": " b2n ",
        "division_code": " nrs ",
        "adjustment_type": "auto_buffer",
        "adjustment_name": "AUTO SPSI",
        "amount": "4000",
        "remarks": "AUTO SPSI | potongan spsi | 4000",
    }, "spsi")
    assert record.emp_code == "B0745"
    assert record.gang_code == "B2N"
    assert record.division_code == "NRS"
    assert record.adjustment_type == "AUTO_BUFFER"
    assert record.adjustment_name == "AUTO SPSI"
    assert record.amount == 4000
    assert record.category_key == "spsi"


def test_category_registry_detects_auto_buffer_names():
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("masa_kerja", "Masa Kerja", "AUTO_BUFFER", ("MASA",), "masa kerja"),
    ])
    assert registry.detect("AUTO SPSI", "AUTO_BUFFER") == "spsi"
    assert registry.detect("AUTO MASA KERJA", "AUTO_BUFFER") == "masa_kerja"


def test_filter_and_row_limit_helpers():
    records = [normalize_record({"emp_code": f"B{i}", "adjustment_name": "AUTO SPSI"}, "spsi") for i in range(3)]
    records.append(normalize_record({"emp_code": "B9", "adjustment_name": "AUTO MASA KERJA"}, "masa_kerja"))
    assert len(filter_by_category(records, "spsi")) == 3
    assert len(apply_row_limit(records, 2)) == 2
