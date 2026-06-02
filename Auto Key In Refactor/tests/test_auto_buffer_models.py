"""Unit tests for app.core.auto_buffer_models."""
from __future__ import annotations

import pytest

from app.core.auto_buffer_models import (
    ADJUSTMENT_NAME_TO_CATEGORY,
    AUTO_BUFFER_COMPARABLE_NAMES,
    AdtransTotal,
    CATEGORY_TO_ADJUSTMENT_NAME,
    ComparisonItem,
    ComparisonResult,
    StoredAdjustment,
    normalize_auto_buffer_adjustment_name,
)


def test_stored_adjustment_is_immutable():
    row = StoredAdjustment(
        emp_code="A0001",
        nik="1234567890",
        adjustment_type="AUTO_BUFFER",
        adjustment_name="TUNJANGAN JABATAN",
        amount=100000.0,
        remarks="seed",
        gang_code="H1H",
        division_code="AB1",
    )
    with pytest.raises(Exception):
        # frozen dataclass raises FrozenInstanceError (subclass of AttributeError)
        row.amount = 200.0  # type: ignore[misc]


def test_comparison_item_status_helpers():
    miss = ComparisonItem(
        emp_code="A0001",
        category="spsi",
        adjustment_name="SPSI",
        stored_amount=4000.0,
        source_amount=0.0,
        diff=-4000.0,
        status="EXTRA_IN_ADJUSTMENTS",
    )
    diff = ComparisonItem(
        emp_code="A0002",
        category="masa_kerja",
        adjustment_name="MASA KERJA",
        stored_amount=300000.0,
        source_amount=250000.0,
        diff=-50000.0,
        status="MISMATCH",
    )
    match = ComparisonItem(
        emp_code="A0003",
        category="tunjangan_jabatan",
        adjustment_name="TUNJANGAN JABATAN",
        stored_amount=500000.0,
        source_amount=500000.0,
        diff=0.0,
        status="MATCH",
    )
    assert miss.is_miss is True
    assert miss.is_diff is False
    assert diff.is_miss is False
    assert diff.is_diff is True
    assert match.is_miss is False
    assert match.is_diff is False


def test_comparison_result_aggregations():
    items = (
        ComparisonItem("A1", "spsi", "SPSI", 4000, 4000, 0, "MATCH"),
        ComparisonItem("A2", "spsi", "SPSI", 4000, 0, -4000, "EXTRA_IN_ADJUSTMENTS"),
        ComparisonItem("A3", "spsi", "SPSI", 4000, 3000, -1000, "MISMATCH"),
    )
    result = ComparisonResult(
        division="AB1",
        period_month=4,
        period_year=2026,
        comparisons=items,
        match_count=1,
        mismatch_count=1,
        extra_count=1,
    )
    assert result.total == 3
    miss_diff = result.miss_and_diff
    assert len(miss_diff) == 2
    assert {item.status for item in miss_diff} == {"EXTRA_IN_ADJUSTMENTS", "MISMATCH"}


def test_normalize_auto_buffer_adjustment_name():
    assert normalize_auto_buffer_adjustment_name("AUTO TUNJANGAN JABATAN") == "TUNJANGAN JABATAN"
    assert normalize_auto_buffer_adjustment_name("  tunjangan  jabatan ") == "TUNJANGAN JABATAN"
    assert normalize_auto_buffer_adjustment_name("") == ""
    assert normalize_auto_buffer_adjustment_name("MASA KERJA") == "MASA KERJA"
    assert normalize_auto_buffer_adjustment_name("auto masa kerja") == "MASA KERJA"


def test_category_mapping_is_consistent():
    # Forward & reverse maps must be in sync.
    for category, name in CATEGORY_TO_ADJUSTMENT_NAME.items():
        assert ADJUSTMENT_NAME_TO_CATEGORY[name] == category
    for name in AUTO_BUFFER_COMPARABLE_NAMES:
        assert name in ADJUSTMENT_NAME_TO_CATEGORY


def test_adtrans_total_basic():
    total = AdtransTotal(emp_code="A0001", category="spsi", amount=4000.0)
    assert total.emp_code == "A0001"
    assert total.category == "spsi"
    assert total.amount == pytest.approx(4000.0)
