from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.core.query_gateway import (
    DEFAULT_QUERY_GATEWAY_BASE_URL,
    DEFAULT_QUERY_GATEWAY_DATABASE,
    DEFAULT_QUERY_GATEWAY_SERVER,
    PlantwareDbPtrjGateway,
    QueryGatewayConfig,
    QueryGatewayError,
)


ENV_NAMES = (
    "AUTO_KEY_IN_QUERY_GATEWAY_BASE_URL",
    "QUERY_GATEWAY_BASE_URL",
    "AUTO_KEY_IN_QUERY_GATEWAY_API_KEY",
    "QUERY_GATEWAY_API_KEY",
    "AUTO_KEY_IN_QUERY_GATEWAY_SERVER",
    "QUERY_GATEWAY_SERVER",
    "AUTO_KEY_IN_QUERY_GATEWAY_DATABASE",
    "QUERY_GATEWAY_DATABASE",
    "AUTO_KEY_IN_QUERY_GATEWAY_TIMEOUT_SECONDS",
    "QUERY_GATEWAY_TIMEOUT_SECONDS",
)


def gateway_response(payload: dict) -> Mock:
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def clear_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_query_gateway_config_defaults_to_plantware_server2_db_ptrj(monkeypatch: pytest.MonkeyPatch):
    clear_gateway_env(monkeypatch)

    config = QueryGatewayConfig.from_env(load_dotenv_file=False)

    assert config.base_url == DEFAULT_QUERY_GATEWAY_BASE_URL
    assert config.server == DEFAULT_QUERY_GATEWAY_SERVER
    assert config.database == DEFAULT_QUERY_GATEWAY_DATABASE
    assert config.timeout_seconds == 30


def test_query_gateway_config_reads_auto_key_in_env(monkeypatch: pytest.MonkeyPatch):
    clear_gateway_env(monkeypatch)
    monkeypatch.setenv("AUTO_KEY_IN_QUERY_GATEWAY_BASE_URL", "http://10.0.0.110:8001/")
    monkeypatch.setenv("AUTO_KEY_IN_QUERY_GATEWAY_API_KEY", "secret")
    monkeypatch.setenv("AUTO_KEY_IN_QUERY_GATEWAY_SERVER", "server_profile_2")
    monkeypatch.setenv("AUTO_KEY_IN_QUERY_GATEWAY_DATABASE", "db_ptrj")
    monkeypatch.setenv("AUTO_KEY_IN_QUERY_GATEWAY_TIMEOUT_SECONDS", "45")

    config = QueryGatewayConfig.from_env(load_dotenv_file=False)

    assert config.normalized_base_url() == "http://10.0.0.110:8001"
    assert config.api_key == "secret"
    assert config.server == "SERVER_PROFILE_2"
    assert config.database == "db_ptrj"
    assert config.timeout_seconds == 45


def test_health_uses_gateway_health_without_api_key():
    session = Mock()
    session.request.return_value = gateway_response({"status": "ok"})
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    assert client.health() == {"status": "ok"}
    session.request.assert_called_once_with(
        "GET",
        "http://localhost:8001/health",
        params=None,
        json=None,
        headers={},
        timeout=30,
    )


def test_list_servers_and_databases_use_auth_and_server2_default():
    session = Mock()
    session.request.side_effect = [
        gateway_response({
            "success": True,
            "data": {
                "servers": [
                    {"name": "SERVER_PROFILE_2", "host": "10.0.0.2", "readOnly": True},
                    "ignored",
                ]
            },
        }),
        gateway_response({
            "success": True,
            "server": "SERVER_PROFILE_2",
            "data": {"databases": ["db_ptrj", "master"]},
        }),
    ]
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    assert client.list_servers() == [{"name": "SERVER_PROFILE_2", "host": "10.0.0.2", "readOnly": True}]
    assert client.list_databases() == ["db_ptrj", "master"]
    second_call = session.request.call_args_list[1]
    assert second_call.kwargs["params"] == {"server": "SERVER_PROFILE_2"}
    assert second_call.kwargs["headers"] == {"x-api-key": "secret"}


def test_execute_posts_query_to_db_ptrj_on_server2():
    session = Mock()
    session.request.return_value = gateway_response({
        "success": True,
        "server": "SERVER_PROFILE_2",
        "db": "db_ptrj",
        "execution_ms": 9.5,
        "data": {
            "recordset": [{"EmpCode": "B001", "amount": 4000}],
            "rowsAffected": [1],
        },
        "error": None,
    })
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    result = client.execute(" SELECT TOP 1 * FROM PR_ADTRANS ", params={"empCode": "B001"})

    assert result.server == "SERVER_PROFILE_2"
    assert result.database == "db_ptrj"
    assert result.recordset == [{"EmpCode": "B001", "amount": 4000}]
    assert result.rows_affected == [1]
    assert result.execution_ms == 9.5
    assert session.request.call_args.kwargs["json"] == {
        "sql": "SELECT TOP 1 * FROM PR_ADTRANS",
        "server": "SERVER_PROFILE_2",
        "database": "db_ptrj",
        "params": {"empCode": "B001"},
    }


def test_fetch_all_returns_recordset():
    session = Mock()
    session.request.return_value = gateway_response({
        "success": True,
        "server": "SERVER_PROFILE_2",
        "db": "db_ptrj",
        "execution_ms": 1,
        "data": {"recordset": [{"health_check": 1}], "rowsAffected": [1]},
    })
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    assert client.fetch_all("SELECT 1 AS health_check") == [{"health_check": 1}]


def test_execute_rejects_empty_sql_before_gateway_call():
    session = Mock()
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    with pytest.raises(QueryGatewayError, match="SQL query must not be empty"):
        client.execute("   ")
    session.request.assert_not_called()


def test_authenticated_calls_require_api_key():
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key=""), session=Mock())

    with pytest.raises(QueryGatewayError, match="AUTO_KEY_IN_QUERY_GATEWAY_API_KEY"):
        client.list_databases()


def test_gateway_success_false_raises_clear_error():
    session = Mock()
    session.request.return_value = gateway_response({"success": False, "error": "Server profile missing"})
    client = PlantwareDbPtrjGateway(QueryGatewayConfig(api_key="secret"), session=session)

    with pytest.raises(QueryGatewayError, match="Server profile missing"):
        client.list_databases()
