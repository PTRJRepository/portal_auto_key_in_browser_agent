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
from app.ui.division_run_dialog import DivisionFetchWorker, DivisionRunDialog
from app.ui.main_window import FetchWorker, MainWindow, build_premium_retry_plan, build_premium_retry_plan_from_sync_status, sync_status_ids_for_records, verified_sync_status_ids
from app.core.models import AutomationOption, DuplicateDocIdTarget, RunPayload, normalize_record
from app.core.run_service import DbVerificationDecision, apply_row_limit, evaluate_db_ptrj_status, filter_by_category


def test_app_config_fallback_uses_api_division_alias(tmp_path):
    missing_config = tmp_path / "missing.json"
    config = load_app_config(missing_config)
    assert config.default_division_code == "AB1"


def test_main_window_defaults_to_ab1_premi_category():
    config = AppConfig()
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1"), DivisionOption("P1B", "Estate P1B")])

    assert window._selected_division_code() == "AB1"
    assert window.category.currentData() == "premi"
    assert window.adjustment_type.currentText() == "PREMI"
    window.close()


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

def test_manual_adjustment_query_supports_grouped_metadata_filters():
    query = ManualAdjustmentQuery(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        adjustment_type="PREMI",
        view="grouped",
        metadata_only=True,
    )

    assert query.params() == {
        "period_month": "4",
        "period_year": "2026",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "view": "grouped",
        "metadata_only": "true",
    }


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


def test_normalize_record_preserves_employee_identity_fields():
    record = normalize_record({
        "emp_code": "1902054607770001",
        "emp_name": "SURYANTI",
        "nik": "1902054607770001",
        "adjustment_name": "AUTO MASA KERJA",
    }, "masa_kerja")

    assert record.emp_code == "1902054607770001"
    assert record.emp_name == "SURYANTI"
    assert record.nik == "1902054607770001"
    assert record.to_runner_dict()["emp_name"] == "SURYANTI"
    assert record.to_runner_dict()["nik"] == "1902054607770001"

def test_normalize_record_normalizes_negative_amounts_to_positive_values():
    record = normalize_record({
        "emp_code": "b0128",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI ANGKUT",
        "amount": "-684355",
        "jumlah": "-684355",
    }, "premi")

    assert record.amount == 684355
    assert record.jumlah == 684355
    assert record.to_runner_dict()["amount"] == 684355
    assert record.to_runner_dict()["jumlah"] == 684355

def test_normalize_record_maps_nomor_kendaraan_to_vehicle_fields():
    record = normalize_record({
        "emp_code": "b0128",
        "gang_code": "b1t",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI ANGKUT",
        "detail_type": "kendaraan",
        "NOMOR_KENDARAAN": "t0020",
        "expense_code": "driver",
        "jumlah": 684355,
    }, "premi")

    assert record.detail_type == "kendaraan"
    assert record.vehicle_code == "T0020"
    assert record.expense_code == "DRIVER"
    assert record.vehicle_expense_code == "DRIVER"
    assert "T0020" in record.detail_key

def test_normalize_record_reads_block_detail_from_metadata_json():
    record = normalize_record({
        "id": 77,
        "emp_code": "b0128",
        "gang_code": "b1t",
        "division_code": "P1B",
        "adjustment_type": "POTONGAN_KOTOR",
        "adjustment_name": "KOREKSI PANEN",
        "amount": 300000,
        "metadata_json": "{\"input_type\":\"blok\",\"items\":[{\"subblok\":\"P09/01\",\"field_code\":\"B 1\",\"expense_code\":\"L\",\"jumlah\":125000}]}",
    }, "potongan_upah_kotor")

    assert record.detail_type == "blok"
    assert record.subblok == "P0901"
    assert record.subblok_raw == "P09/01"
    assert record.divisioncode == "B 1"
    assert record.expense_code == "L"
    assert record.amount == 125000
    assert record.jumlah == 125000

def test_normalize_record_reads_vehicle_detail_from_metadata_json():
    record = normalize_record({
        "id": 78,
        "emp_code": "b0128",
        "gang_code": "b1t",
        "division_code": "P1B",
        "adjustment_type": "POTONGAN_KOTOR",
        "adjustment_name": "KOREKSI ANGKUT",
        "amount": 684355,
        "metadata_json": "{\"input_type\":\"kendaraan\",\"items\":[{\"nomor_kendaraan\":\"T0020\",\"expense_code\":\"DRIVER\",\"jumlah\":684355}]}",
    }, "potongan_upah_kotor")

    assert record.detail_type == "kendaraan"
    assert record.vehicle_code == "T0020"
    assert record.expense_code == "DRIVER"
    assert record.vehicle_expense_code == "DRIVER"
    assert record.amount == 684355

def test_get_adjustments_flattens_grouped_premium_transactions():
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "view": "grouped",
        "metadata_only": True,
        "data": [
            {
                "division_code": "AB1",
                "gangs": [
                    {
                        "gang_code": "G1H",
                        "employees": [
                            {
                                "emp_code": "A0001",
                                "nik": "1902050504860001",
                                "emp_name": "AHMAD DARYONO",
                                "gang_code": "G1H",
                                "estate": "AB1",
                                "estate_code": "AB1",
                                "division_code": "AB1",
                                "premium_transactions": [
                                    {
                                        "transaction_index": 1,
                                        "adjustment_id": 7,
                                        "adjustment_type": "PREMI",
                                        "adjustment_name": "PREMI PRUNING",
                                        "estate": "AB1",
                                        "estate_code": "AB1",
                                        "division_code": "G 1",
                                        "detail_type": "blok",
                                        "subblok": "P0901",
                                        "subblok_raw": "P09/01",
                                        "jumlah": 304000,
                                        "amount": 304000,
                                        "ad_code": "AL3PM2201",
                                        "ad_code_desc": "(AL) TUNJANGAN PREMI ((PM) HARVESTING)",
                                        "task_code": "AL3PM2201AB1",
                                    },
                                    {
                                        "transaction_index": 2,
                                        "adjustment_id": 7,
                                        "adjustment_type": "PREMI",
                                        "adjustment_name": "PREMI PRUNING",
                                        "detail_type": "blok",
                                        "subblok": "P0902",
                                        "subblok_raw": "P09/02",
                                        "jumlah": 200900,
                                        "amount": 200900,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    with patch("app.core.api_client.requests.get", return_value=response) as get:
        records = client.get_adjustments(ManualAdjustmentQuery(
            period_month=4,
            period_year=2026,
            division_code="AB1",
            adjustment_type="PREMI",
            view="grouped",
            metadata_only=True,
        ))

    get.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/by-api-key",
        params={
            "period_month": "4",
            "period_year": "2026",
            "division_code": "AB1",
            "adjustment_type": "PREMI",
            "view": "grouped",
            "metadata_only": "true",
        },
        headers={"X-API-Key": "secret"},
        timeout=30,
    )
    response.raise_for_status.assert_called_once()
    assert [record.amount for record in records] == [304000, 200900]
    assert records[0].emp_code == "A0001"
    assert records[0].emp_name == "AHMAD DARYONO"
    assert records[0].nik == "1902050504860001"
    assert records[0].gang_code == "G1H"
    assert records[0].division_code == "AB1"
    assert records[0].estate == "AB1"
    assert records[0].divisioncode == "G 1"
    assert records[0].detail_type == "blok"
    assert records[0].subblok == "P0901"
    assert records[0].subblok_raw == "P09/01"
    assert records[0].jumlah == 304000
    assert records[0].transaction_index == 1
    assert records[0].adjustment_id == 7
    assert records[0].ad_code == "AL3PM2201"
    assert records[0].ad_code_desc == "(AL) TUNJANGAN PREMI ((PM) HARVESTING)"
    assert records[0].description == "PREMI PRUNING"
    assert records[0].task_desc == "(AL) TUNJANGAN PREMI ((PM) HARVESTING)"
    assert records[0].task_code == "AL3PM2201AB1"
    assert records[0].to_runner_dict()["ad_code_desc"] == "(AL) TUNJANGAN PREMI ((PM) HARVESTING)"
    assert records[0].to_runner_dict()["description"] == "PREMI PRUNING"
    assert records[0].category_key == "premi"

def test_grouped_premium_derives_plantware_divisioncode_from_gang_when_transaction_division_is_estate():
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "view": "grouped",
        "data": [
            {
                "division_code": "AB1",
                "gangs": [
                    {
                        "gang_code": "G1H",
                        "employees": [
                            {
                                "emp_code": "G0597",
                                "emp_name": "ABDURRAHMAN",
                                "gang_code": "G1H",
                                "estate": "AB1",
                                "premium_transactions": [
                                    {
                                        "transaction_index": 1,
                                        "adjustment_id": 42258,
                                        "adjustment_type": "PREMI",
                                        "adjustment_name": "PREMI PRUNING",
                                        "division_code": "AB1",
                                        "detail_type": "blok",
                                        "subblok": "P08/06",
                                        "amount": 304000,
                                        "ad_code": "AL3PM0601",
                                        "ad_code_desc": "(AL) TUNJANGAN PREMI ((PM) PRUNING)",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    with patch("app.core.api_client.requests.get", return_value=response):
        records = client.get_adjustments(ManualAdjustmentQuery(
            period_month=4,
            period_year=2026,
            division_code="AB1",
            adjustment_type="PREMI",
            view="grouped",
            metadata_only=True,
        ))

    assert records[0].division_code == "AB1"
    assert records[0].divisioncode == "G 1"
    assert records[0].subblok == "P0806"
    assert records[0].description == "PREMI PRUNING"


def test_get_adjustments_flattens_vehicle_based_premium_detail_items():
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "view": "grouped",
        "metadata_only": True,
        "data": [
            {
                "division_code": "PG1B",
                "estate": "P1B",
                "gangs": [
                    {
                        "gang_code": "B1T",
                        "employees": [
                            {
                                "emp_code": "B0128",
                                "emp_name": "DRIVER TEST",
                                "gang_code": "B1T",
                                "estate": "P1B",
                                "premiums": [
                                    {
                                        "id": 91,
                                        "adjustment_type": "PREMI",
                                        "adjustment_name": "PREMI ANGKUT",
                                        "amount": 684355,
                                        "ad_code": "AL3PT2304",
                                        "ad_code_desc": "(AL) TUNJANGAN PREMI ((PM) DRIVER - ANGKUT TBK)",
                                        "metadata_json": "{\"input_type\":\"kendaraan\",\"items\":[{\"nomor_kendaraan\":\"T0020\",\"expense_code\":\"DRIVER\",\"jumlah\":684355}],\"total_amount\":684355}",
                                        "detail_items": [
                                            {
                                                "detail_type": "kendaraan",
                                                "nomor_kendaraan": "T0020",
                                                "expense_code": "DRIVER",
                                                "jumlah": 684355,
                                                "amount": 684355,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    with patch("app.core.api_client.requests.get", return_value=response):
        records = client.get_adjustments(ManualAdjustmentQuery(
            period_month=4,
            period_year=2026,
            division_code="P1B",
            adjustment_type="PREMI",
            adjustment_name="PREMI ANGKUT",
            view="grouped",
            metadata_only=True,
        ))

    assert len(records) == 1
    assert records[0].emp_code == "B0128"
    assert records[0].gang_code == "B1T"
    assert records[0].division_code == "P1B"
    assert records[0].divisioncode == "B 1"
    assert records[0].adjustment_name == "PREMI ANGKUT"
    assert records[0].detail_type == "kendaraan"
    assert records[0].vehicle_code == "T0020"
    assert records[0].expense_code == "DRIVER"
    assert records[0].vehicle_expense_code == "DRIVER"
    assert records[0].amount == 684355
    assert records[0].adjustment_id == 91
    assert "T0020" in records[0].detail_key

def test_get_adjustments_flattens_flat_koreksi_detail_items():
    registry = CategoryRegistry([
        AdjustmentCategory("potongan_upah_kotor", "Potongan Upah Kotor", "POTONGAN_KOTOR", ("KOREKSI",), "potongan"),
    ])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": [
            {
                "id": 77,
                "period_month": 4,
                "period_year": 2026,
                "emp_code": "B0128",
                "emp_name": "KOREKSI TEST",
                "gang_code": "B1T",
                "division_code": "P1B",
                "adjustment_type": "POTONGAN_KOTOR",
                "adjustment_name": "KOREKSI PANEN",
                "amount": 300000,
                "ad_code": "DE0001",
                "ad_code_desc": "(DE) KOREKSI PANEN",
                "detail_items": [
                    {
                        "detail_type": "blok",
                        "subblok": "P09/01",
                        "field_code": "B 1",
                        "expense_code": "L",
                        "jumlah": 125000,
                    },
                    {
                        "detail_type": "blok",
                        "subblok": "P09/02",
                        "field_code": "B 1",
                        "expense_code": "L",
                        "jumlah": 175000,
                    },
                ],
            }
        ],
    }

    with patch("app.core.api_client.requests.get", return_value=response):
        records = client.get_adjustments(ManualAdjustmentQuery(
            period_month=4,
            period_year=2026,
            division_code="P1B",
            adjustment_type="POTONGAN_KOTOR",
            adjustment_name="KOREKSI PANEN",
        ))

    assert [record.amount for record in records] == [125000, 175000]
    assert [record.detail_type for record in records] == ["blok", "blok"]
    assert [record.subblok for record in records] == ["P0901", "P0902"]
    assert [record.divisioncode for record in records] == ["B 1", "B 1"]
    assert all(record.adjustment_id == 77 for record in records)
    assert all(record.category_key == "potongan_upah_kotor" for record in records)


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

def test_get_adjustment_name_options_calls_new_endpoint_and_normalizes_by_type():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002/", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "count": 2,
        "adjustment_names_by_type": {
            "PREMI": ["PREMI PRUNING"],
            "POTONGAN_KOTOR": ["KOREKSI PANEN"],
        },
        "by_type": {
            "PREMI": [
                {
                    "adjustment_type": "PREMI",
                    "adjustment_name": "PREMI PRUNING",
                }
            ],
            "POTONGAN_KOTOR": [
                {
                    "adjustment_type": "POTONGAN_KOTOR",
                    "adjustment_name": "KOREKSI PANEN",
                }
            ],
        },
    }

    with patch("app.core.api_client.requests.get", return_value=response) as get:
        options = client.get_adjustment_name_options(
            period_month=4,
            period_year=2026,
            division_code="ab1",
            gang_code="g1h",
            emp_code="g0597",
            adjustment_type="PREMI,POTONGAN_KOTOR",
            metadata_only=True,
            search="premi",
            limit=200,
        )

    get.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/adjustment-name-options/by-api-key",
        params={"period_month": "4", "period_year": "2026", "division_code": "AB1", "gang_code": "G1H", "emp_code": "G0597", "adjustment_type": "PREMI,POTONGAN_KOTOR", "metadata_only": "true", "search": "premi", "limit": "200"},
        headers={"X-API-Key": "secret"},
        timeout=30,
    )
    assert [option.adjustment_name for option in options] == ["PREMI PRUNING", "KOREKSI PANEN"]
    assert options[0].ad_code == ""
    assert options[0].task_desc == ""
    assert options[1].category == ""

def test_fetch_worker_enriches_manual_records_with_automation_options_not_adjustment_name_options():
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
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1A", gang_code="G1H", emp_code="G0597", adjustment_type="PREMI"))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    enriched = completed[0][0][0]
    assert enriched.ad_code == "A100"
    assert enriched.description == "INSENTIF PANEN"
    assert enriched.task_code == "A100P1A"
    assert enriched.task_desc == "(AL) INSENTIF PANEN"
    client.get_adjustment_name_options.assert_not_called()
    client.get_automation_options.assert_called_once_with(
        division_code="P1A",
        categories=["premi"],
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
    client.get_adjustment_name_options.side_effect = RuntimeError("404 Not Found")
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="P1B", adjustment_type="PREMI"))
    completed = []
    failed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert completed[0][0] == [record]

def test_main_window_refreshes_adjustment_names_for_premi_category():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1")])
    window.gang_code.setText("g1h")
    window.emp_code.setText("g0597")
    option = AutomationOption(
        category="premi",
        adjustment_type="PREMI",
        adjustment_name="PREMI PRUNING",
        ad_code="AL0001",
        description="PREMI PRUNING",
        task_code="AL0001AB1",
        task_desc="(AL) PREMI PRUNING",
        base_task_code="AL0001",
        loc_code="AB1",
    )

    with patch.object(ManualAdjustmentApiClient, "get_adjustment_name_options", return_value=[option]) as get_options:
        window.apply_category_preset()

    get_options.assert_called_once_with(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        gang_code="G1H",
        emp_code="G0597",
        adjustment_type="PREMI",
        metadata_only=True,
        search=None,
        limit=200,
    )
    assert window.adjustment_name.count() == 1
    assert window.adjustment_name.itemText(0) == "PREMI PRUNING"
    window.close()

def test_main_window_premi_refresh_ignores_stale_adjustment_name_text():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1")])
    window.gang_code.setText("g1h")
    window.adjustment_name.setText("PREMI LAMA")

    with patch.object(ManualAdjustmentApiClient, "get_adjustment_name_options", return_value=[]) as get_options:
        window._refresh_adjustment_name_options()

    get_options.assert_called_once_with(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        gang_code="G1H",
        emp_code=None,
        adjustment_type="PREMI",
        metadata_only=True,
        search=None,
        limit=200,
    )
    window.close()

def test_main_window_shows_loading_while_refreshing_adjustment_names():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1")])
    observed = []

    def fake_options(*args, **kwargs):
        observed.append((window.adjustment_name.text(), window.refresh_adjustment_names_button.isEnabled()))
        return []

    with patch.object(ManualAdjustmentApiClient, "get_adjustment_name_options", side_effect=fake_options):
        window.apply_category_preset()

    assert observed == [("Loading adjustment names...", False)]
    assert window.refresh_adjustment_names_button.isEnabled() is True
    window.close()


def test_main_window_refreshes_adjustment_names_when_category_changes():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
        AdjustmentCategory("potongan_upah_bersih", "Potongan Upah Bersih", "POTONGAN_BERSIH", ("POTONGAN_BERSIH",), "potongan_upah_bersih"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1")])
    option = AutomationOption(
        category="potongan_upah_bersih",
        adjustment_type="POTONGAN_BERSIH",
        adjustment_name="POTONGAN PINJAMAN",
        ad_code="AL0002",
        description="POTONGAN PINJAMAN",
        task_code="AL0002AB1",
        task_desc="(AL) POTONGAN PINJAMAN",
        base_task_code="AL0002",
        loc_code="AB1",
    )

    with patch.object(ManualAdjustmentApiClient, "get_adjustment_name_options", return_value=[option]) as get_options:
        window.category.setCurrentIndex(1)

    get_options.assert_called_with(
        period_month=4,
        period_year=2026,
        division_code="AB1",
        gang_code=None,
        emp_code=None,
        adjustment_type="POTONGAN_BERSIH",
        metadata_only=None,
        search=None,
        limit=200,
    )
    assert window.adjustment_name.itemText(0) == "POTONGAN PINJAMAN"
    window.close()


def test_main_window_adcode_preview_prefers_task_desc_display_for_premium_details():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate AB1")])
    record = normalize_record({
        "emp_code": "G0597",
        "division_code": "AB1",
        "gang_code": "G1H",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
        "ad_code": "AL3PM0601",
        "ad_code_desc": "(AL) TUNJANGAN PREMI ((PM) PRUNING)",
        "detail_type": "blok",
        "subblok": "P0801",
    }, "premi")

    assert window._adcode_for_record(record) == "(AL) TUNJANGAN PREMI ((PM) PRUNING)"
    window.close()

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


def test_sync_status_posts_verification_payload():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    payload = {"success": True, "data": {"updated_count": 2, "partial_count": 0, "rows": []}}
    response = Mock()
    response.json.return_value = payload

    with patch("app.core.api_client.requests.post", return_value=response) as post:
        result = client.sync_status(
            period_month=4,
            period_year=2026,
            division_code="ab1",
            adjustment_type="PREMI",
            ids=[10, 11],
            dry_run=True,
            only_if_adtrans_exists=True,
            updated_by="browser_automation",
        )

    post.assert_called_once_with(
        "http://localhost:8002/payroll/manual-adjustment/sync-status/by-api-key",
        json={
            "period_month": 4,
            "period_year": 2026,
            "division_code": "AB1",
            "adjustment_type": "PREMI",
            "ids": [10, 11],
            "sync_status": "SYNC",
            "only_if_adtrans_exists": True,
            "dry_run": True,
            "updated_by": "browser_automation",
        },
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

def test_division_fetch_worker_enriches_manual_records_with_automation_options():
    record = normalize_record({
        "emp_code": "a0001",
        "division_code": "ab1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
    }, "premi")
    option = AutomationOption(
        category="premi",
        adjustment_type="PREMI",
        adjustment_name="PREMI PRUNING",
        ad_code="AL0001",
        description="PREMI PRUNING",
        task_code="AL0001AB1",
        task_desc="(AL) PREMI PRUNING",
        base_task_code="AL0001",
        loc_code="AB1",
    )
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.get_automation_options.return_value = [option]
    worker = DivisionFetchWorker(client, 4, 2026, "AB1", "premi", "PREMI", None)

    records = worker.run()

    assert records[0].ad_code == "AL0001"
    client.get_adjustment_name_options.assert_not_called()
    client.get_automation_options.assert_called_once_with(
        division_code="AB1",
        categories=["premi"],
        limit=200,
    )


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


def test_get_duplicate_delete_targets_keeps_newest_per_premium_doc_desc():
    registry = CategoryRegistry([])
    client = ManualAdjustmentApiClient("http://localhost:8002", "secret", registry)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {
            "duplicate_report": {
                "duplicates": [
                    {
                        "emp_code": "l0073",
                        "emp_name": "BAHARUDIN",
                        "category": "premi",
                        "keep_doc_id": "ADIJL26044355",
                        "records": [
                            {"id": "10", "doc_id": "ADIJL26044012", "doc_date": "2026-04-30", "doc_desc": "PREMI INSENTIF PANEN", "amount": 150000, "action": "DELETE_OLD"},
                            {"id": "11", "doc_id": "ADIJL26044030", "doc_date": "2026-04-30", "doc_desc": "PREMI TBS", "amount": 1046398, "action": "DELETE_OLD"},
                            {"id": "20", "doc_id": "ADIJL26044346", "doc_date": "2026-04-30", "doc_desc": "PREMI INSENTIF PANEN", "amount": 150000, "action": "DELETE_OLD"},
                            {"id": "21", "doc_id": "ADIJL26044355", "doc_date": "2026-04-30", "doc_desc": "PREMI TBS", "amount": 1046398, "action": "KEEP_NEWEST"},
                        ],
                    }
                ]
            }
        },
    }

    with patch("app.core.api_client.requests.post", return_value=response):
        targets = client.get_duplicate_delete_targets(4, 2026, "IJL", ["premi"])

    assert [target.doc_id for target in targets] == ["ADIJL26044012", "ADIJL26044030"]
    assert [target.keep_doc_id for target in targets] == ["ADIJL26044346", "ADIJL26044355"]


def test_duplicate_cleanup_category_can_target_premi_filter():
    config = AppConfig(default_division_code="IJL")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("IJL", "Ijuk")])

    index = window.duplicate_category.findData("premi")
    assert index >= 0
    window.duplicate_category.setCurrentIndex(index)

    assert window.duplicate_filters.text() == "premi"
    assert window._duplicate_category_supported() is True
    window.close()


def test_duplicate_cleanup_button_text_tracks_dry_run_state():
    config = AppConfig(default_division_code="IJL")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("IJL", "Ijuk")])

    assert window.duplicate_dry_run.isChecked() is True
    assert window.delete_duplicates_button.text() == "Scan Selected Duplicates (Dry Run)"

    window.duplicate_dry_run.setChecked(False)

    assert window.delete_duplicates_button.text() == "Delete Selected Duplicates"
    window.close()

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
    assert window.process_only_miss.isChecked() is True
    window.close()


def test_non_premium_manual_fetch_preview_ignores_miss_only_filter():
    config = AppConfig(default_division_code="P1B")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("spsi", "SPSI", "AUTO_BUFFER", ("SPSI",), "spsi"),
        AdjustmentCategory("potongan_upah_kotor", "Potongan Upah Kotor", "POTONGAN_KOTOR", ("POTONGAN",), "potongan"),
    ])
    window = MainWindow(config, registry, [DivisionOption("P1B", "Estate")])
    window.category.setCurrentIndex(1)
    window.process_only_miss.setChecked(True)
    record = normalize_record({
        "emp_code": "B0732",
        "gang_code": "B1H",
        "division_code": "PG1B",
        "adjustment_type": "POTONGAN_KOTOR",
        "adjustment_name": "POTONGAN LAIN",
        "amount": 0,
        "remarks": "INIT_COLUMN - Kolom ditambahkan tanpa nilai",
    }, "potongan_upah_kotor")

    window._handle_fetch_completed([record], {})

    assert window.records_table.rowCount() == 1
    assert window.records_table.item(0, 4).text() == "B0732"
    assert window.records_table.item(0, 7).text() == "POTONGAN LAIN"
    window.close()

def test_premi_fetch_preview_filters_verified_match_in_retry_safe_mode():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate")])
    window.process_only_miss.setChecked(True)
    matched = normalize_record({
        "emp_code": "G0597",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
    }, "premi")
    missing = normalize_record({
        "emp_code": "G0600",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 200000,
    }, "premi")

    window._handle_fetch_completed([matched, missing], {
        ("G0597", "premi"): {"status": "VERIFIED_MATCH", "expected": 100000, "actual": 100000},
        ("G0600", "premi"): {"status": "VERIFIED_NOT_FOUND", "expected": 200000, "actual": 0},
    })

    assert window.records_table.rowCount() == 1
    assert window.records_table.item(0, 4).text() == "G0600"
    window.close()

def test_premi_fetch_preview_marks_verified_match_as_already_in_db_when_not_filtered():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate")])
    window.process_only_miss.setChecked(False)
    matched = normalize_record({
        "emp_code": "G0597",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
    }, "premi")
    missing = normalize_record({
        "emp_code": "G0600",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 200000,
    }, "premi")

    window._handle_fetch_completed([matched, missing], {
        ("G0597", "premi"): {"status": "VERIFIED_MATCH", "expected": 100000, "actual": 100000},
        ("G0600", "premi"): {"status": "VERIFIED_NOT_FOUND", "expected": 200000, "actual": 0},
    })

    assert window.records_table.rowCount() == 2
    assert window.records_table.item(0, 1).text() == "Already in DB"
    assert window.records_table.item(1, 1).text() == "Missing in DB"
    window.close()

def test_premi_fetch_preview_keeps_only_missing_complement_for_unique_partial_match():
    config = AppConfig(default_division_code="AB1")
    QApplication.instance() or QApplication([])
    registry = CategoryRegistry([
        AdjustmentCategory("premi", "Premi", "PREMI", ("PREMI",), "premi"),
    ])
    window = MainWindow(config, registry, [DivisionOption("AB1", "Estate")])
    window.process_only_miss.setChecked(True)
    already_1 = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
        "transaction_index": 1,
    }, "premi")
    already_2 = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 250000,
        "transaction_index": 2,
    }, "premi")
    missing = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "gang_code": "G1H",
        "division_code": "AB1",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI TBS",
        "amount": 400000,
        "transaction_index": 3,
    }, "premi")

    window._handle_fetch_completed([already_1, already_2, missing], {
        ("G0597", "premi"): {"status": "VERIFIED_MISMATCH", "expected": 750000, "actual": 350000},
    })

    assert window.records_table.rowCount() == 1
    assert window.records_table.item(0, 7).text() == "PREMI TBS"
    assert window.records_table.item(0, 11).text() == "400000"
    window.close()

def test_premium_retry_plan_holds_ambiguous_partial_match():
    records = [
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI A", "amount": 100000, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI B", "amount": 200000, "transaction_index": 2}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI C", "amount": 300000, "transaction_index": 3}, "premi"),
    ]

    allowed, held = build_premium_retry_plan(records, {
        ("G0597", "premi"): {"status": "VERIFIED_MISMATCH", "expected": 600000, "actual": 300000},
    })

    assert allowed == set()
    assert held == {("G0597", "premi"): "ambiguous partial match"}

def test_premium_retry_plan_uses_sync_status_per_adjustment_row():
    records = [
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 100000, "adjustment_id": 10, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 200000, "adjustment_id": 10, "transaction_index": 2}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 400000, "adjustment_id": 11, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 500000, "adjustment_id": 11, "transaction_index": 2}, "premi"),
    ]

    allowed, held = build_premium_retry_plan_from_sync_status(records, {
        "data": {
            "rows": [
                {"id": 10, "status": "SKIPPED", "skip_reason": "UNCHANGED", "target_amount": 300000, "adtrans_amount": 300000},
                {"id": 11, "status": "SKIPPED", "skip_reason": "ADTRANS_AMOUNT_PARTIAL", "target_amount": 900000, "adtrans_amount": 400000},
            ]
        }
    })

    assert allowed == {records[3].record_key}
    assert held == {}

def test_premium_retry_plan_holds_ambiguous_sync_status_partial_row():
    records = [
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 100000, "adjustment_id": 11, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 200000, "adjustment_id": 11, "transaction_index": 2}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 300000, "adjustment_id": 11, "transaction_index": 3}, "premi"),
    ]

    allowed, held = build_premium_retry_plan_from_sync_status(records, {
        "data": {
            "rows": [
                {"id": 11, "status": "SKIPPED", "skip_reason": "ADTRANS_AMOUNT_PARTIAL", "target_amount": 600000, "adtrans_amount": 300000},
            ]
        }
    })

    assert allowed == set()
    assert held == {("G0597", "premi", "11"): "ambiguous partial match"}

def test_verified_sync_status_ids_excludes_partial_and_not_found_rows():
    payload = {
        "data": {
            "rows": [
                {"id": 10, "status": "UPDATED", "target_amount": 300000, "adtrans_amount": 300000},
                {"id": 11, "status": "SKIPPED", "skip_reason": "ADTRANS_AMOUNT_PARTIAL", "target_amount": 900000, "adtrans_amount": 400000},
                {"id": 12, "status": "SKIPPED", "skip_reason": "ADTRANS_NOT_FOUND", "target_amount": 100000, "adtrans_amount": 0},
                {"id": 13, "status": "UNCHANGED", "target_amount": 250000, "adtrans_amount": 250000},
            ]
        }
    }

    assert verified_sync_status_ids(payload) == [10, 13]

def test_sync_status_ids_for_records_uses_unique_manual_adjustment_ids():
    records = [
        normalize_record({"id": 10, "adjustment_id": 10, "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 100000, "transaction_index": 1}, "premi"),
        normalize_record({"id": 10, "adjustment_id": 10, "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 200000, "transaction_index": 2}, "premi"),
        normalize_record({"id": 11, "adjustment_id": 11, "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS", "amount": 400000, "transaction_index": 1}, "premi"),
    ]

    assert sync_status_ids_for_records(records) == [10, 11]

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

def test_row_success_queues_sync_status_verification_for_manual_adjustment_id(monkeypatch):
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="AB1"), CategoryRegistry([]), [DivisionOption("AB1", "Estate")])
    record = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 100000,
        "adjustment_id": 10,
    }, "premi")
    drain = Mock()
    monkeypatch.setattr(window, "_drain_sync_status_queue", drain, raising=False)
    window.set_records([record])

    window._update_record_from_event("row.success", {"emp_code": "G0597", "adjustment_name": "PREMI PRUNING", "detail_key": record.detail_key, "tab_index": 0}, "row add confirmed")

    assert window.records_table.item(0, 0).text() == "Input Done"
    assert window.records_table.item(0, 2).text() == "QUEUED"
    assert window.summary_table.item(0, 2).text() == "QUEUED"
    assert getattr(window, "pending_sync_status_ids", set()) == {10}
    drain.assert_called_once()
    window.close()

def test_sync_status_completed_updates_all_detail_rows_for_adjustment_id():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="AB1"), CategoryRegistry([]), [DivisionOption("AB1", "Estate")])
    records = [
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 100000, "adjustment_id": 10, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 200000, "adjustment_id": 10, "transaction_index": 2}, "premi"),
    ]
    window.set_records(records)

    window._handle_sync_status_completed({
        "dry_run": {"data": {"rows": [{"id": 10, "status": "UPDATED", "target_amount": 300000, "adtrans_amount": 300000, "new_sync_status": "SYNC"}]}},
        "apply": {"data": {"updated_count": 1, "rows": [{"id": 10, "status": "UPDATED", "target_amount": 300000, "adtrans_amount": 300000, "new_sync_status": "SYNC"}]}},
        "verified_ids": [10],
    })

    assert window.records_table.item(0, 2).text() == "SYNC"
    assert window.records_table.item(1, 2).text() == "SYNC"
    assert window.records_table.item(0, 3).text() == "UPDATED 300000/300000"
    assert window.summary_table.item(1, 2).text() == "SYNC"
    window.close()

def test_sync_status_completed_marks_partial_rows_without_syncing():
    QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig(default_division_code="AB1"), CategoryRegistry([]), [DivisionOption("AB1", "Estate")])
    record = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 500000,
        "adjustment_id": 14,
    }, "premi")
    window.set_records([record])

    window._handle_sync_status_completed({
        "dry_run": {"data": {"rows": [{"id": 14, "status": "SKIPPED", "skip_reason": "ADTRANS_AMOUNT_PARTIAL", "target_amount": 500000, "adtrans_amount": 350000}]}},
        "apply": None,
        "verified_ids": [],
    })

    assert window.records_table.item(0, 2).text() == "PARTIAL"
    assert window.records_table.item(0, 3).text() == "ADTRANS_AMOUNT_PARTIAL 350000/500000"
    assert window.summary_table.item(0, 2).text() == "PARTIAL"
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


def test_fetch_worker_verifies_premium_records_even_without_stale_remarks():
    record = normalize_record({
        "emp_code": "G0597",
        "adjustment_name": "PREMI PRUNING",
        "adjustment_type": "PREMI",
        "amount": 100000,
        "remarks": "",
    }, "premi")
    client = Mock()
    client.get_adjustments.return_value = [record]
    client.check_adtrans.return_value = [{"emp_code": "G0597", "premi": 100000}]
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, adjustment_type="PREMI"))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][1][("G0597", "premi")]["status"] == "VERIFIED_MATCH"
    client.check_adtrans.assert_called_once_with(4, 2026, ["G0597"], ["premi"])

def test_fetch_worker_prefers_sync_status_for_premium_retry_plan():
    records = [
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 100000, "adjustment_id": 10, "transaction_index": 1}, "premi"),
        normalize_record({"period_month": 4, "period_year": 2026, "emp_code": "G0597", "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING", "amount": 200000, "adjustment_id": 10, "transaction_index": 2}, "premi"),
    ]
    client = Mock()
    client.get_adjustments.return_value = records
    client.sync_status.return_value = {
        "data": {
            "rows": [
                {"id": 10, "status": "SKIPPED", "skip_reason": "ADTRANS_AMOUNT_PARTIAL", "target_amount": 300000, "adtrans_amount": 100000},
            ]
        }
    }
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="AB1", adjustment_type="PREMI"))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][1]["source"] == "sync-status"
    assert completed[0][1]["retry_record_keys"] == {records[1].record_key}
    client.sync_status.assert_called_once()
    client.check_adtrans.assert_not_called()

def test_fetch_worker_does_not_reverify_premium_records_already_sync_in_remarks():
    record = normalize_record({
        "period_month": 4,
        "period_year": 2026,
        "emp_code": "G0597",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "amount": 493350,
        "adjustment_id": 10,
        "remarks": "PREMI PRUNING | AL3PM0601 - (AL) TUNJANGAN PREMI ((PM) PRUNING) | 493350 | sync:SYNC | match:MANUAL | SEED_IMPORT_AB1",
    }, "premi")
    client = Mock()
    client.get_adjustments.return_value = [record]
    worker = FetchWorker(client, ManualAdjustmentQuery(period_month=4, period_year=2026, division_code="AB1", adjustment_type="PREMI"))
    completed = []
    worker.completed.connect(lambda records, verification: completed.append((records, verification)))

    worker.run()

    assert completed[0][0] == [record]
    assert completed[0][1] == {}
    client.sync_status.assert_not_called()
    client.check_adtrans.assert_not_called()

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
