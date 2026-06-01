from __future__ import annotations

from unittest.mock import Mock

from app.core.loosefruit_gateway import (
    LoosefruitGatewayRepository,
    normalize_loosefruit_duplicate_row,
)


def test_loosefruit_query_uses_gateway_and_literal_underscore_pattern():
    gateway = Mock()
    gateway.fetch_all.return_value = [
        {
            "ID": 100,
            "DocID": "LF001_01",
            "DocDate": "2026-05-15T00:00:00.000Z",
            "DocDesc": "LOOSEFRUIT",
            "LocCode": "P1B",
            "AccMonth": 5,
            "AccYear": 2026,
            "PhyMonth": 5,
            "PhyYear": 2026,
            "Status": "OPEN",
            "AutoCalMT": "1.5",
            "TotalMT": "2.0",
        }
    ]
    repo = LoosefruitGatewayRepository(gateway)

    rows = repo.list_duplicate_doc_ids(loc_code="p1b", phy_month=5, phy_year=2026, limit=50)

    sql = gateway.fetch_all.call_args.args[0]
    params = gateway.fetch_all.call_args.kwargs["params"]
    assert "FROM [dbo].[PR_LOOSEFRUIT]" in sql
    assert "SELECT TOP (50)" in sql
    assert "[DocID] LIKE @docIdPattern" in sql
    assert "ESCAPE" in sql
    assert params["docIdPattern"] == "%\\_%"
    assert params["locCode"] == "P1B"
    assert params["phyMonth"] == 5
    assert params["phyYear"] == 2026
    assert rows[0].doc_id == "LF001_01"
    assert rows[0].loc_code == "P1B"


def test_loosefruit_limit_is_clamped():
    gateway = Mock()
    gateway.fetch_all.return_value = []
    repo = LoosefruitGatewayRepository(gateway)

    repo.list_duplicate_doc_ids(limit=999999)

    assert "SELECT TOP (10000)" in gateway.fetch_all.call_args.args[0]


def test_loosefruit_duplicate_row_maps_to_runner_target():
    row = normalize_loosefruit_duplicate_row({
        "ID": "100",
        "DocID": "LF001_01",
        "DocDate": "2026-05-15T00:00:00.000Z",
        "DocDesc": "LOOSEFRUIT",
        "LocCode": "p1b",
        "AccMonth": "5",
        "AccYear": "2026",
        "PhyMonth": "5",
        "PhyYear": "2026",
        "Status": "OPEN",
        "AutoCalMT": "1.5",
        "TotalMT": "2.0",
    })

    target = row.to_duplicate_target()

    assert target.master_id == "100"
    assert target.doc_id == "LF001_01"
    assert target.doc_desc == "LOOSEFRUIT"
    assert target.amount == 2.0
    assert target.action == "DELETE_RECORD"
    assert target.category == "loosefruit"
    assert target.raw["source"] == "loosefruit-pr-loosefruit"
    assert target.raw["table"] == "db_ptrj.dbo.PR_LOOSEFRUIT"


def test_loosefruit_blank_loc_code_fetches_all():
    gateway = Mock()
    gateway.fetch_all.return_value = []
    repo = LoosefruitGatewayRepository(gateway)

    repo.list_duplicate_doc_ids(loc_code="", phy_month=5, phy_year=2026)

    params = gateway.fetch_all.call_args.kwargs["params"]
    assert "locCode" not in params
    sql = gateway.fetch_all.call_args.args[0]
    assert "[LocCode] = @locCode" not in sql
