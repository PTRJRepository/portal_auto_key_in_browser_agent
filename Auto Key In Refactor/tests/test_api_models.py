import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.core.category_registry import AdjustmentCategory, CategoryRegistry
from app.core.api_client import ManualAdjustmentApiClient, ManualAdjustmentQuery
from app.core.config import AppConfig, DivisionOption, load_app_config, load_divisions
from PySide6.QtWidgets import QApplication

from app.ui.division_monitor import CategoryStatus, DetailDialog, DivisionCard, DivisionMonitorWorker, MissDetail
from app.ui.division_run_dialog import DivisionRunDialog
from app.ui.main_window import FetchWorker, MainWindow
from app.core.models import AutomationOption, DuplicateDocIdTarget, RunPayload, normalize_record
from app.core.run_service import DbVerificationDecision, apply_row_limit, evaluate_db_ptrj_status, filter_by_category


def test_app_config_fallback_uses_api_division_alias(tmp_path):
    missing_config = tmp_path / "missing.json"
    config = load_app_config(missing_config)
    assert config.default_division_code == "P1B"


def test_manual_adjustment_query_omits_empty_optional_filters():
    query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="AB1", gang_code="")
    assert query.params() == {"period_month": "4", "period_year": "2026", "division_code": "AB1"}

def test_manual_adjustment_query_maps_pg_division_alias_for_manual_types_only():
    premi_query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="PREMI")
    manual_query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="MANUAL")
    comma_query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="PREMI,POTONGAN_KOTOR")
    auto_query = ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="AUTO_BUFFER")

    assert premi_query.params()["division_code"] == "PG1B"
    assert manual_query.params()["division_code"] == "PG1B"
    assert comma_query.params()["division_code"] == "PG1B"
    assert comma_query.params()["adjustment_type"] == "PREMI,POTONGAN_KOTOR"
    assert auto_query.params()["division_code"] == "P1B"


def test_main_window_adjustment_type_includes_manual_alias():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        AppConfig(),
        CategoryRegistry([]),
        [DivisionOption("P1B", "P1B", ())],
    )

    values = [window.adjustment_type.itemText(index) for index in range(window.adjustment_type.count())]

    assert "MANUAL" in values


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


def test_premi_category_includes_premi_tunjangan_records():
    records = [
        normalize_record({"emp_code": "A1", "adjustment_type": "PREMI", "adjustment_name": "PREMI PANEN"}, "premi"),
        normalize_record({"emp_code": "A2", "adjustment_type": "PREMI", "adjustment_name": "TUNJANGAN PREMI"}, "premi_tunjangan"),
        normalize_record({"emp_code": "A3", "adjustment_type": "POTONGAN_KOTOR", "adjustment_name": "KOREKSI PANEN"}, "potongan_upah_kotor"),
    ]

    filtered = filter_by_category(records, "premi")

    assert [record.emp_code for record in filtered] == ["A1", "A2"]


def test_category_registry_detects_premi_tunjangan_before_general_premi():
    registry = CategoryRegistry([
        AdjustmentCategory("premi_tunjangan", "Premi Tunjangan", "PREMI", ("TUNJANGAN PREMI",), "premi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
        AdjustmentCategory("potongan_upah_bersih", "Potongan Upah Bersih", "POTONGAN_BERSIH", ("POTONGAN UPAH BERSIH",), "potongan upah bersih"),
    ])
    assert registry.detect("TUNJANGAN PREMI HARVESTING", "PREMI") == "premi_tunjangan"
    assert registry.detect("PREMI COBA", "PREMI") == "premi"
    assert registry.detect("INSENTIF PANEN", "PREMI") == "premi"
    assert registry.detect("POTONGAN PINJAMAN", "POTONGAN_BERSIH") == "potongan_upah_bersih"

def test_normalize_record_preserves_automation_option_fields():
    record = normalize_record({
        "emp_code": "a0001",
        "division_code": "p1a",
        "adjustment_type": "PREMI",
        "adjustment_name": "INSENTIF PANEN",
        "amount": "100000",
        "ad_code": "a100",
        "description": "INSENTIF PANEN",
        "task_code": "A100P1A",
        "task_desc": "(AL) INSENTIF PANEN",
        "base_task_code": "A100",
        "loc_code": "P1A",
    }, "premi")

    assert record.ad_code == "A100"
    assert record.description == "INSENTIF PANEN"
    assert record.task_code == "A100P1A"
    assert record.task_desc == "(AL) INSENTIF PANEN"
    assert record.base_task_code == "A100"
    assert record.loc_code == "P1A"
    assert record.to_runner_dict()["ad_code"] == "A100"


def test_remarks_based_categories_use_pipe_adcode_and_description():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
        AdjustmentCategory("koreksi", "Koreksi", "POTONGAN_KOTOR", ("KOREKSI",), ""),
        AdjustmentCategory("potongan_upah_bersih", "Potongan Upah Bersih", "POTONGAN_BERSIH", ("POTONGAN UPAH BERSIH",), ""),
    ])
    window = MainWindow(AppConfig(default_division_code="P1B"), registry, [DivisionOption("P1B", "Estate")])
    records = [
        normalize_record({"adjustment_name": "PREMI PANEN", "remarks": "PREMI PANEN | premi | 15000", "amount": 15000}, "premi"),
        normalize_record({"adjustment_name": "KOREKSI UPAH", "remarks": "KOREKSI UPAH | koreksi | 5000", "amount": 5000}, "koreksi"),
        normalize_record({"adjustment_name": "POTONGAN UPAH BERSIH", "remarks": "POTONGAN UPAH BERSIH | potongan upah bersih | 7000", "amount": 7000}, "potongan_upah_bersih"),
    ]

    assert [window._adcode_for_record(record) for record in records] == ["premi", "koreksi", "potongan upah bersih"]
    assert [window._description_for_record(record) for record in records] == ["PREMI PANEN", "KOREKSI UPAH", "POTONGAN UPAH BERSIH"]
    window.close()

def test_manual_record_adcode_prefers_api_field_before_category_default():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(AppConfig(default_division_code="P1B"), registry, [DivisionOption("P1B", "Estate")])
    record = normalize_record({
        "adjustment_type": "PREMI",
        "adjustment_name": "INSENTIF PANEN",
        "amount": 100000,
        "ad_code": "A100",
    }, "premi")

    assert window._adcode_for_record(record) == "A100"
    assert window._description_for_record(record) == "INSENTIF PANEN"
    window.close()


def test_potongan_upah_bersih_preset():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("potongan_upah_bersih", "Potongan Upah Bersih", "POTONGAN_BERSIH", ("POTONGAN UPAH BERSIH",), "potongan upah bersih"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.adjustment_name.setText("AUTO SPSI")
    window.category.setCurrentIndex(1)
    window.apply_category_preset()

    assert window.adjustment_type.currentText() == "POTONGAN_BERSIH"
    assert window.adjustment_name.text() == ""
    assert window.only_missing.isChecked() is False
    assert window.process_only_miss.isChecked() is False
    window.close()


def test_filter_for_record_maps_all_category_keys():
    from app.ui.main_window import filter_for_record
    records = [
        normalize_record({"adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi"),
        normalize_record({"adjustment_name": "AUTO MASA KERJA", "amount": 25000}, "masa_kerja"),
        normalize_record({"adjustment_name": "AUTO TUNJANGAN JABATAN", "amount": 150000}, "tunjangan_jabatan"),
        normalize_record({"adjustment_name": "PREMI PANEN", "amount": 15000}, "premi"),
        normalize_record({"adjustment_name": "TUNJANGAN PREMI", "amount": 20000}, "premi_tunjangan"),
        normalize_record({"adjustment_name": "POTONGAN UPAH", "amount": 5000}, "potongan_upah_kotor"),
        normalize_record({"adjustment_name": "POTONGAN UPAH BERSIH", "amount": 7000}, "potongan_upah_bersih"),
    ]
    expected = ["spsi", "masa kerja", "jabatan", "premi", "premi", "potongan", "potongan upah bersih"]
    assert [filter_for_record(r) for r in records] == expected


def test_potongan_upah_bersih_preset():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("potongan_upah_bersih", "Potongan Upah Bersih", "POTONGAN_BERSIH", ("POTONGAN UPAH BERSIH",), "potongan upah bersih"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.adjustment_name.setText("AUTO SPSI")
    window.category.setCurrentIndex(1)
    window.apply_category_preset()

    assert window.adjustment_type.currentText() == "POTONGAN_BERSIH"
    assert window.adjustment_name.text() == ""
    assert window.only_missing.isChecked() is False
    assert window.process_only_miss.isChecked() is False
    window.close()


def test_filter_for_record_maps_all_category_keys():
    from app.ui.main_window import filter_for_record
    records = [
        normalize_record({"adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi"),
        normalize_record({"adjustment_name": "AUTO MASA KERJA", "amount": 25000}, "masa_kerja"),
        normalize_record({"adjustment_name": "AUTO TUNJANGAN JABATAN", "amount": 150000}, "tunjangan_jabatan"),
        normalize_record({"adjustment_name": "PREMI PANEN", "amount": 15000}, "premi"),
        normalize_record({"adjustment_name": "TUNJANGAN PREMI", "amount": 20000}, "premi_tunjangan"),
        normalize_record({"adjustment_name": "POTONGAN UPAH", "amount": 5000}, "potongan_upah_kotor"),
        normalize_record({"adjustment_name": "POTONGAN UPAH BERSIH", "amount": 7000}, "potongan_upah_bersih"),
    ]
    expected = ["spsi", "masa kerja", "jabatan", "premi", "premi", "potongan", "potongan upah bersih"]
    assert [filter_for_record(r) for r in records] == expected


def test_evaluate_db_ptrj_status_marks_missing_when_actual_is_zero():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=0)
    assert decision == DbVerificationDecision("Missing in DB", False, "")


def test_evaluate_db_ptrj_status_marks_already_in_db_when_amount_matches():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=4000)
    assert decision == DbVerificationDecision("Already in DB", True, "already exists in db_ptrj; skipped automatically")


def test_evaluate_db_ptrj_status_marks_mismatch_and_skips():
    decision = evaluate_db_ptrj_status(expected_amount=4000, actual_amount=3000)
    assert decision == DbVerificationDecision("DB Mismatch", True, "db_ptrj amount 3000 differs from expected 4000; skipped automatically")


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


def test_check_adtrans_accepts_latest_totals_response_shape():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {
            "totals": [{"emp_code": "B0065", "spsi": 4000}],
            "duplicate_report": {"duplicate_count": 0, "duplicates": []},
        },
    }

    with patch("app.core.api_client.requests.post", return_value=response):
        result = client.check_adtrans(4, 2026, ["B0065"], ["spsi"])

    assert result == [{"emp_code": "B0065", "spsi": 4000}]


def test_get_automation_options_calls_latest_endpoint_and_normalizes_fields():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": [
            {
                "category": "premi",
                "adjustment_type": "PREMI",
                "adjustment_name": "INSENTIF PANEN",
                "ad_code": "a100",
                "description": "INSENTIF PANEN",
                "task_code": "A100P1A",
                "task_desc": "(AL) INSENTIF PANEN",
                "base_task_code": "A100",
                "loc_code": "P1A",
            }
        ],
    }

    with patch("app.core.api_client.requests.get", return_value=response) as get:
        options = client.get_automation_options(
            division_code="p1a",
            categories=["premi", "koreksi", "potongan_upah_bersih"],
            search="panen",
            limit=200,
        )

    get.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/automation-options/by-api-key",
        params={"division_code": "P1A", "categories": "premi,koreksi,potongan_upah_bersih", "search": "panen", "limit": "200"},
        headers={"X-API-Key": "secret"},
        timeout=30,
    )
    assert options == [
        AutomationOption(
            category="premi",
            adjustment_type="PREMI",
            adjustment_name="INSENTIF PANEN",
            ad_code="A100",
            description="INSENTIF PANEN",
            task_code="A100P1A",
            task_desc="(AL) INSENTIF PANEN",
            base_task_code="A100",
            loc_code="P1A",
        )
    ]

def test_fetch_worker_enriches_manual_records_with_automation_options():
    record = normalize_record({
        "emp_code": "a0001",
        "division_code": "p1a",
        "adjustment_type": "PREMI",
        "adjustment_name": "INSENTIF PANEN",
        "amount": 100000,
    }, "premi")
    option = AutomationOption(
        category="premi",
        adjustment_type="PREMI",
        adjustment_name="INSENTIF PANEN",
        ad_code="A100",
        description="INSENTIF PANEN",
        task_code="A100P1A",
        task_desc="(AL) INSENTIF PANEN",
        base_task_code="A100",
        loc_code="P1A",
    )
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.get_automation_options.return_value = [option]
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1A", adjustment_type="PREMI"))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    enriched = completed[0][0][0]
    assert enriched.ad_code == "A100"
    assert enriched.description == "INSENTIF PANEN"
    assert enriched.task_code == "A100P1A"
    assert enriched.task_desc == "(AL) INSENTIF PANEN"
    client.get_automation_options.assert_called_once_with(
        division_code="P1A",
        categories=["premi", "koreksi", "potongan_upah_bersih"],
        limit=200,
    )

def test_fetch_worker_keeps_manual_records_when_automation_options_endpoint_missing():
    record = normalize_record({
        "emp_code": "a0001",
        "division_code": "pg1b",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PANEN",
        "amount": 100000,
    }, "premi")
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.get_automation_options.side_effect = RuntimeError("404 Not Found")
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="PREMI"))
    completed = []
    failed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert completed[0][0] == [record]

def test_check_adtrans_raises_on_success_false():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    response = Mock()
    response.json.return_value = {"success": False, "message": "bad filter"}

    with patch("app.core.api_client.requests.post", return_value=response), pytest.raises(RuntimeError, match="bad filter"):
        client.check_adtrans(4, 2026, ["B0065"], ["spsi"])


def test_compare_adtrans_posts_division_payload():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    payload = {"success": True, "data": {"comparisons": []}}
    response = Mock()
    response.json.return_value = payload

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.compare_adtrans(4, 2026, "p2a", filters=["spsi"])

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/compare-adtrans/by-api-key",
        json={"period_month": 4, "period_year": 2026, "division_code": "P2A", "filters": ["spsi"]},
        headers={"Content-Type": "application/json", "X-API-Key": "secret"},
        timeout=30,
    )
    assert result == payload


def test_sync_adtrans_posts_sync_mode_payload():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    payload = {"success": True, "data": {"synced_count": 2, "skipped_match": 1}}
    response = Mock()
    response.json.return_value = payload

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.sync_adtrans(4, 2026, "p2a", filters=["spsi"], sync_mode="MISMATCH_AND_MISSING")

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/sync-adtrans/by-api-key",
        json={"period_month": 4, "period_year": 2026, "division_code": "P2A", "sync_mode": "MISMATCH_AND_MISSING", "filters": ["spsi"]},
        headers={"Content-Type": "application/json", "X-API-Key": "secret"},
        timeout=30,
    )
    assert result == payload


def test_reverse_compare_adtrans_posts_division_payload():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    payload = {"success": True, "data": {"comparisons": []}}
    response = Mock()
    response.json.return_value = payload

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.reverse_compare_adtrans(4, 2026, "nrs", filters=["spsi", "masa kerja"])

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/reverse-compare-adtrans/by-api-key",
        json={"period_month": 4, "period_year": 2026, "division_code": "NRS", "filters": ["spsi", "masa kerja"]},
        headers={"Content-Type": "application/json", "X-API-Key": "secret"},
        timeout=30,
    )
    assert result == payload


def test_division_monitor_parses_reverse_compare_response_and_maps_pg_division_code():
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("masa_kerja", "Masa Kerja", "AUTO_BUFFER", ("MASA",), "masa kerja"),
        AdjustmentCategory("tunjangan_jabatan", "Tunjangan Jabatan", "AUTO_BUFFER", ("JABATAN",), "jabatan"),
        AdjustmentCategory("premi_tunjangan", "Premi Tunjangan", "PREMI", ("TUNJANGAN PREMI",), "premi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
        AdjustmentCategory("potongan_upah_kotor", "Potongan Upah Kotor", "POTONGAN_KOTOR", ("POTONGAN", "KOREKSI"), "potongan"),
    ])
    client = Mock()
    client.categories = registry
    client.compare_adtrans.return_value = {
        "success": True,
        "data": {
            "comparisons": [
                {"emp_code": "G0007", "category": "spsi", "adjustment_name": "AUTO SPSI", "source_amount": 4000, "stored_amount": 4000, "status": "MATCH", "gang_code": "G1H"},
                {"emp_code": "G0010", "category": "jabatan", "adjustment_name": "AUTO TUNJANGAN JABATAN", "source_amount": 150000, "stored_amount": 0, "status": "MISMATCH", "gang_code": "G1H"},
            ]
        },
    }
    client.reverse_compare_adtrans.return_value = {
        "success": True,
        "data": {
            "comparisons": [
                {"emp_code": "G0015", "category": "masa kerja", "adjustment_name": "AUTO MASA KERJA", "source_amount": 0, "stored_amount": 25000, "status": "EXTRA_IN_ADJUSTMENTS", "gang_code": None},
            ]
        },
    }
    worker = DivisionMonitorWorker(client, 4, 2026, ["P1B"], ["spsi", "masa_kerja", "tunjangan_jabatan", "premi"])

    summary = worker._process_division("P1B")

    client.compare_adtrans.assert_called_once_with(4, 2026, "PG1B", filters=["jabatan", "masa kerja", "premi", "spsi"])
    client.reverse_compare_adtrans.assert_called_once_with(4, 2026, "PG1B", filters=["jabatan", "masa kerja", "premi", "spsi"])
    assert summary.categories["spsi"].match == 1
    assert summary.categories["tunjangan_jabatan"].mismatch == 1
    assert summary.categories["masa_kerja"].miss == 1
    assert summary.categories["masa_kerja"].miss_amount == 25000
    assert summary.categories["masa_kerja"].miss_details[0].emp_code == "G0015"


def test_division_monitor_parses_forward_missing_and_mismatch_details():
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("potongan_upah_kotor", "Potongan Upah Kotor", "POTONGAN_KOTOR", ("POTONGAN", "KOREKSI"), "potongan"),
    ])
    client = Mock()
    client.categories = registry
    client.compare_adtrans.return_value = {
        "success": True,
        "data": {
            "comparisons": [
                {"emp_code": "B0065", "category": "spsi", "adjustment_name": "AUTO SPSI", "source_amount": 4000, "stored_amount": None, "status": "MISSING", "gang_code": "B2N", "doc_desc": "POTONGAN SPSI"},
                {"emp_code": "B0070", "category": "potongan", "adjustment_name": "KOREKSI PANEN", "source_amount": 5000, "stored_amount": 2000, "status": "MISMATCH", "gang_code": "B2N", "doc_desc": "KOREKSI PANEN", "remarks": "AD CODE: DE0001 - KOREKSI PANEN"},
            ]
        },
    }
    client.reverse_compare_adtrans.return_value = {"success": True, "data": {"comparisons": []}}
    worker = DivisionMonitorWorker(client, 4, 2026, ["NRS"], ["spsi", "potongan_upah_kotor"])

    summary = worker._process_division("NRS")

    client.compare_adtrans.assert_called_once_with(4, 2026, "NRS", filters=["koreksi", "potongan", "spsi"])
    assert summary.categories["spsi"].missing == 1
    assert summary.categories["spsi"].missing_amount == 4000
    assert summary.categories["spsi"].missing_details[0].status == "MISSING"
    assert summary.categories["spsi"].missing_details[0].db_doc_desc == "POTONGAN SPSI"
    assert summary.categories["potongan_upah_kotor"].mismatch == 1
    assert summary.categories["potongan_upah_kotor"].mismatch_amount == 3000
    assert summary.categories["potongan_upah_kotor"].mismatch_details[0].adjustment_name == "KOREKSI PANEN"
    assert summary.categories["potongan_upah_kotor"].mismatch_details[0].remarks == "AD CODE: DE0001 - KOREKSI PANEN"


def test_division_monitor_reverse_compare_keeps_virtual_division_code():
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    client = Mock()
    client.categories = registry
    client.compare_adtrans.return_value = {"success": True, "data": {"comparisons": []}}
    client.reverse_compare_adtrans.return_value = {"success": True, "data": {"comparisons": []}}
    worker = DivisionMonitorWorker(client, 4, 2026, ["NRS"], ["spsi"])

    worker._process_division("NRS")

    client.compare_adtrans.assert_called_once_with(4, 2026, "NRS", filters=["spsi"])
    client.reverse_compare_adtrans.assert_called_once_with(4, 2026, "NRS", filters=["spsi"])


def test_division_card_enables_sync_for_mismatch_and_run_for_extra():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    card = DivisionCard("P1B", "Estate", registry)

    card.update_category("spsi", CategoryStatus(total=1, mismatch=1, miss=0))

    widgets = card._category_widgets["spsi"]
    assert widgets["sync_btn"].isEnabled() is True
    assert widgets["run_btn"].isEnabled() is False
    assert widgets["detail_btn"].isEnabled() is True

    card.update_category("spsi", CategoryStatus(total=1, missing=1, miss=0))

    assert widgets["sync_btn"].isEnabled() is True
    assert widgets["run_btn"].isEnabled() is False
    assert widgets["detail_btn"].isEnabled() is True

    card.update_category("spsi", CategoryStatus(total=1, mismatch=0, miss=1, miss_details=[SimpleNamespace(emp_code="B0065")]))

    assert widgets["sync_btn"].isEnabled() is False
    assert widgets["run_btn"].isEnabled() is True
    assert widgets["detail_btn"].isEnabled() is True
    card.close()


def test_division_run_dialog_filters_fetched_records_to_extra_details():
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    dialog = DivisionRunDialog(
        config=AppConfig(default_division_code="P1B"),
        categories=registry,
        api_client=Mock(),
        division_code="P1B",
        division_label="Estate",
        category_key="spsi",
        category_label="SPSI",
        mode="dry_run",
        month=4,
        year=2026,
        extra_details=[SimpleNamespace(emp_code="B0065", adjustment_name="AUTO SPSI")],
    )
    extra = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    unrelated = normalize_record({"emp_code": "B0070", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")

    assert dialog._filter_extra_records([extra, unrelated]) == [extra]
    dialog.close()


def test_detail_dialog_shows_db_ptrj_extend_amounts_docdesc_and_remarks():
    QApplication.instance() or QApplication([])
    detail = MissDetail(
        emp_code="B0065",
        gang_code="B2N",
        adjustment_name="AUTO SPSI",
        source_amount=0,
        stored_amount=4000,
        diff=-4000,
        status="EXTRA_IN_ADJUSTMENTS",
        category_key="spsi",
        category_label="SPSI",
        db_doc_desc="POTONGAN SPSI",
        remarks="AUTO SPSI | potongan spsi | 4000",
    )

    dialog = DetailDialog("NRS", "SPSI", [detail])

    assert dialog.table.horizontalHeaderItem(4).text() == "DocDesc db_ptrj"
    assert dialog.table.item(0, 0).text() == "EXTRA"
    assert dialog.table.item(0, 4).text() == "POTONGAN SPSI"
    assert dialog.table.item(0, 5).text() == "0"
    assert dialog.table.item(0, 6).text() == "4,000"
    assert dialog.table.item(0, 7).text() == "-4,000"
    assert dialog.table.item(0, 8).text() == "AUTO SPSI | potongan spsi | 4000"
    dialog.close()


def test_check_adtrans_report_posts_division_payload_and_preserves_duplicate_report():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    payload = {"success": True, "data": {"duplicate_report": {"duplicates": []}}}
    response = Mock()
    response.json.return_value = payload

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.check_adtrans_report(4, 2026, ["spsi"], division_code="p2a")

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/check-adtrans/by-api-key",
        json={"period_month": 4, "period_year": 2026, "filters": ["spsi"], "division_code": "P2A"},
        headers={"Content-Type": "application/json", "X-API-Key": "secret"},
        timeout=30,
    )
    assert result == payload


def test_get_duplicate_delete_targets_extracts_only_delete_old_records():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {
            "duplicate_report": {
                "duplicates": [
                    {
                        "emp_code": "c0096",
                        "emp_name": "SURYANTI",
                        "category": "spsi",
                        "keep_doc_id": "ADP2A26041462",
                        "records": [
                            {"id": "674422", "doc_id": "ADP2A26041201", "doc_date": "2026-04-27", "doc_desc": "POTONGAN SPSI", "amount": 4000, "action": "delete_old"},
                            {"id": "674653", "doc_id": "ADP2A26041462", "doc_date": "2026-04-27", "doc_desc": "POTONGAN SPSI", "amount": 4000, "action": "KEEP_NEWEST"},
                        ],
                    }
                ]
            }
        },
    }

    with patch("app.core.api_client.requests.post", return_value=response):
        targets = client.get_duplicate_delete_targets(4, 2026, "P2A", ["spsi"])

    assert targets == [
        DuplicateDocIdTarget(
            master_id="674422",
            doc_id="ADP2A26041201",
            doc_date="2026-04-27",
            emp_code="C0096",
            emp_name="SURYANTI",
            doc_desc="POTONGAN SPSI",
            amount=4000,
            action="DELETE_OLD",
            keep_doc_id="ADP2A26041462",
            category="spsi",
            raw={"id": "674422", "doc_id": "ADP2A26041201", "doc_date": "2026-04-27", "doc_desc": "POTONGAN SPSI", "amount": 4000, "action": "delete_old"},
        )
    ]


def test_run_payload_serializes_duplicate_targets():
    target = DuplicateDocIdTarget("1", "AD1", "2026-04-27", "C0001", "Name", "POTONGAN SPSI", 4000, "DELETE_OLD", "AD2", "spsi", {"id": "1"})
    payload = RunPayload(4, 2026, "P2A", None, None, "AUTO_BUFFER", "AUTO SPSI", "spsi", "multi_tab_shared_session", 1, True, True, None, [], operation="delete_duplicates", duplicate_targets=[target], delete_dry_run=False)

    assert payload.to_json_dict()["operation"] == "delete_duplicates"
    assert payload.to_json_dict()["delete_dry_run"] is False
    assert payload.to_json_dict()["duplicate_targets"][0]["doc_id"] == "AD1"


def test_add_job_button_registers_current_config_in_job_table():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])

    window.add_job_from_current_config()

    assert window.add_job_button.text() == "Tambahkan Job"
    assert window.job_table.rowCount() == 1
    assert window.job_table.item(0, 1).text() == "P1B"
    assert window.job_table.item(0, 3).text() == "spsi"
    assert window.job_table.item(0, 9).text() == "Pending"
    window.close()


def test_premi_preset_fetches_all_premi_names():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.adjustment_name.setText("AUTO SPSI")
    window.category.setCurrentIndex(1)
    window.apply_category_preset()

    assert window.adjustment_type.currentText() == "PREMI"
    assert window.adjustment_name.text() == ""
    assert window.only_missing.isChecked() is False
    assert window.process_only_miss.isChecked() is False
    window.close()


def test_manual_fetch_preview_ignores_miss_only_filter():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.category.setCurrentIndex(1)
    window.process_only_miss.setChecked(True)
    record = normalize_record({
        "emp_code": "B0732",
        "gang_code": "B1H",
        "division_code": "PG1B",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PANEN",
        "amount": 0,
        "remarks": "INIT_COLUMN - Kolom ditambahkan tanpa nilai",
    }, "premi")

    window._handle_fetch_completed([record], {})

    assert window.records_table.rowCount() == 1
    assert window.records_table.item(0, 4).text() == "B0732"
    assert window.records_table.item(0, 7).text() == "PREMI PANEN"
    window.close()

def test_selected_jobs_create_payloads_from_saved_config():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi")])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.gang_code.setText("b2n")
    window.row_limit.setValue(5)
    window.max_tabs.setValue(3)
    window.add_job_from_current_config()

    payload = window.build_payload_from_job(window.selected_jobs()[0], [])

    assert window.run_selected_jobs_button.text() == "Run Selected Jobs"
    assert payload.division_code == "P1B"
    assert payload.gang_code == "B2N"
    assert payload.category_key == "spsi"
    assert payload.max_tabs == 3
    assert payload.row_limit == 5
    window.close()


def test_records_table_tracks_input_and_db_status_separately():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    window = MainWindow(config, CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")

    window.set_records([record])

    assert window.records_table.horizontalHeaderItem(0).text() == "Input Status"
    assert window.records_table.horizontalHeaderItem(1).text() == "DB Status"
    assert window.records_table.item(0, 0).text() == "Pending"
    assert window.records_table.item(0, 1).text() == "Not Checked"
    window.close()


def test_row_success_marks_input_done_green():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000}, "spsi")
    window.set_records([record])

    window._update_record_from_event("row.success", {"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "tab_index": 0}, "row add confirmed")

    assert window.records_table.item(0, 0).text() == "Input Done"
    assert window.record_status[window._record_key(record)]["input_status"] == "Input Done"
    window.close()


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


def test_verified_match_and_mismatch_are_not_treated_as_missing():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="P1B"), CategoryRegistry([]), [DivisionOption("P1B", "Estate")])
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000, "remarks": "sync:MISS"}, "spsi")

    assert window._record_is_miss(record) is True
    window.fetch_verification_status[("B0065", "spsi")] = {"status": "VERIFIED_MATCH", "actual": 4000, "expected": 4000}
    assert window._record_is_miss(record) is False
    window.fetch_verification_status[("B0065", "spsi")] = {"status": "VERIFIED_MISMATCH", "actual": 3000, "expected": 4000}
    assert window._record_is_miss(record) is False
    window.fetch_verification_status[("B0065", "spsi")] = {"status": "VERIFIED_NOT_FOUND", "actual": 0, "expected": 4000}
    assert window._record_is_miss(record) is True
    window.close()


def test_fetch_worker_verifies_stale_missing_records_against_db_ptrj():
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000, "remarks": "sync:MISS"}, "spsi")
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.check_adtrans.return_value = [{"emp_code": "B0065", "spsi": 4000}]
    query = ManualAdjustmentQuery(period_month=4, period_year=2026)
    worker = FetchWorker(client, query)
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][0] == [record]
    assert completed[0][1][("B0065", "spsi")]["status"] == "VERIFIED_MATCH"
    client.check_adtrans.assert_called_once_with(4, 2026, ["B0065"], ["spsi"])


def test_fetch_worker_sums_duplicate_emp_filter_before_verification():
    records = [
        normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 2000, "remarks": "sync:MISS"}, "spsi"),
        normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 2000, "remarks": "match:MISMATCH"}, "spsi"),
    ]
    client = Mock()
    client.get_adjustments.return_value = records
    client.check_adtrans.return_value = [{"emp_code": "B0065", "spsi": 4000}]
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][1][("B0065", "spsi")]["expected"] == 4000
    assert completed[0][1][("B0065", "spsi")]["status"] == "VERIFIED_MATCH"


def test_fetch_worker_keeps_records_when_db_ptrj_verification_fails():
    record = normalize_record({"emp_code": "B0065", "adjustment_name": "AUTO SPSI", "amount": 4000, "remarks": "sync:MISS"}, "spsi")
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.check_adtrans.side_effect = RuntimeError("db down")
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][0] == [record]
    assert completed[0][1][("B0065", "spsi")]["status"] == "VERIFY_ERROR"
    assert "db down" in completed[0][1][("B0065", "spsi")]["message"]
