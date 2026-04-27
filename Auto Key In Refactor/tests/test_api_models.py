import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from app.core.category_registry import AdjustmentCategory, CategoryRegistry
from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.config import AppConfig, DivisionOption, load_app_config, load_divisions
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.core.models import normalize_record
from app.core.run_service import apply_row_limit, filter_by_category


def test_app_config_fallback_uses_api_division_alias(tmp_path):
    missing_config = tmp_path / "missing.json"
    config = load_app_config(missing_config)
    assert config.default_division_code == "P1B"


def test_manual_adjustment_query_omits_empty_optional_filters():
    query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="AB1", gang_code="")
    assert query.params() == {"period_month": "4", "period_year": "2026", "division_code": "AB1"}


def test_load_divisions_uses_location_labels(tmp_path):
    divisions_path = tmp_path / "divisions.json"
    divisions_path.write_text('[{"code":"P1B","label":"ESTATE PARIT GUNUNG 1B","aliases":["PG1B"]}]', encoding="utf-8")
    divisions = load_divisions(divisions_path)
    assert divisions[0].code == "P1B"
    assert divisions[0].label == "ESTATE PARIT GUNUNG 1B"
    assert divisions[0].aliases == ("PG1B",)


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


def test_check_adtrans_posts_expected_payload():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {"success": True, "data": [{"emp_code": "B0065", "spsi": 4000}]}

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.check_adtrans(4, 2026, ["B0065"], ["spsi"])

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/check-adtrans/by-api-key",
        json={"period_month": 4, "period_year": 2026, "emp_codes": ["B0065"], "filters": ["spsi"]},
        headers={"Content-Type": "application/json", "X-API-Key": "secret"},
        timeout=30,
    )
    response.raise_for_status.assert_called_once()
    assert result == [{"emp_code": "B0065", "spsi": 4000}]


def test_check_adtrans_raises_on_success_false():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    response = Mock()
    response.json.return_value = {"success": False, "message": "bad filter"}

    with patch("app.core.api_client.requests.post", return_value=response), pytest.raises(RuntimeError, match="bad filter"):
        client.check_adtrans(4, 2026, ["B0065"], ["spsi"])


def test_scan_session_status_detects_active_division_session(tmp_path):
    session_dir = tmp_path / "runner" / "data" / "sessions"
    session_dir.mkdir(parents=True)
    saved_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    (session_dir / "session-P1B.json").write_text(json.dumps({"sessionId": "session-P1B", "division": "P1B", "savedAt": saved_at.isoformat(), "storageState": {"cookies": [{"name": "ASP.NET_SessionId"}]}}), encoding="utf-8")
    config = AppConfig(runner_command=f"node {tmp_path / 'runner' / 'dist' / 'cli.js'}", default_division_code="P1B")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("P1B", "ESTATE PARIT GUNUNG 1B"), DivisionOption("P2A", "ESTATE PARIT GUNUNG 2A")])

    statuses = window._scan_session_status()
    window.close()

    p1b = next(item for item in statuses if item["code"] == "P1B")
    p2a = next(item for item in statuses if item["code"] == "P2A")
    assert p1b["status"] == "Active"
    assert p1b["active"] is True
    assert p2a["status"] == "— None"
    assert p2a["active"] is False


def test_scan_session_status_marks_expired_session(tmp_path):
    session_dir = tmp_path / "runner" / "data" / "sessions"
    session_dir.mkdir(parents=True)
    saved_at = datetime.now(timezone.utc) - timedelta(minutes=300)
    (session_dir / "session-P1B.json").write_text(json.dumps({"sessionId": "session-P1B", "division": "P1B", "savedAt": saved_at.isoformat(), "storageState": {"cookies": [{"name": "ASP.NET_SessionId"}]}}), encoding="utf-8")
    config = AppConfig(runner_command=f"node {tmp_path / 'runner' / 'dist' / 'cli.js'}", default_division_code="P1B")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("P1B", "ESTATE PARIT GUNUNG 1B")])

    statuses = window._scan_session_status()
    window.close()

    assert statuses[0]["status"] == "Expired"
    assert statuses[0]["active"] is False
