from __future__ import annotations

from unittest.mock import Mock

from app.core.task_register_gateway import (
    TASK_REGISTER_DUPLICATE_CATEGORY,
    TASK_REGISTER_DUPLICATE_SOURCE,
    TaskRegisterGatewayRepository,
    normalize_task_register_duplicate_row,
)


def test_task_register_query_uses_gateway_and_literal_underscore_pattern():
    gateway = Mock()
    gateway.fetch_all.return_value = [
        {
            "ID": 44,
            "DocID": "70897930_01",
            "DocDate": "2026-04-30",
            "LocCode": "p1b",
            "AccMonth": 4,
            "AccYear": 2026,
            "PhyMonth": 4,
            "PhyYear": 2026,
            "Status": "OPEN",
            "TotalAmount": "125000",
        }
    ]
    repo = TaskRegisterGatewayRepository(gateway)

    rows = repo.list_duplicate_doc_ids(loc_code="p1b", phy_month=4, phy_year=2026, limit=25)

    sql = gateway.fetch_all.call_args.args[0]
    params = gateway.fetch_all.call_args.kwargs["params"]
    assert "FROM [dbo].[PR_TASKREG]" in sql
    assert "SELECT TOP (25)" in sql
    assert "[DocID] LIKE @docIdPattern" in sql
    assert "ESCAPE" in sql
    assert "[LocCode] = @locCode" in sql
    assert params == {"docIdPattern": "%\\_%", "locCode": "P1B", "phyMonth": 4, "phyYear": 2026}
    assert rows[0].doc_id == "70897930_01"
    assert rows[0].loc_code == "P1B"


def test_task_register_limit_is_clamped():
    gateway = Mock()
    gateway.fetch_all.return_value = []
    repo = TaskRegisterGatewayRepository(gateway)

    repo.list_duplicate_doc_ids(limit=999999)

    assert "SELECT TOP (10000)" in gateway.fetch_all.call_args.args[0]


def test_task_register_duplicate_row_maps_to_runner_target():
    row = normalize_task_register_duplicate_row({
        "ID": "44",
        "DocID": "70897930_01",
        "DocDate": "2026-04-30T00:00:00.000Z",
        "LocCode": "p1b",
        "AccMonth": "4",
        "AccYear": "2026",
        "PhyMonth": "4",
        "PhyYear": "2026",
        "Status": "OPEN",
        "TotalAmount": "125000.5",
    })

    target = row.to_duplicate_target()

    assert target.master_id == "44"
    assert target.doc_id == "70897930_01"
    assert target.doc_desc == "TASK REGISTER"
    assert target.amount == 125000.5
    assert target.action == "DELETE_RECORD"
    assert target.category == TASK_REGISTER_DUPLICATE_CATEGORY
    assert target.raw["source"] == TASK_REGISTER_DUPLICATE_SOURCE
    assert target.raw["loc_code"] == "P1B"
