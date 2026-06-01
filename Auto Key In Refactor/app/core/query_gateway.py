from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Mapping

import requests

DEFAULT_QUERY_GATEWAY_BASE_URL = "http://localhost:8001"
DEFAULT_QUERY_GATEWAY_SERVER = "SERVER_PROFILE_2"
DEFAULT_QUERY_GATEWAY_DATABASE = "db_ptrj"
DEFAULT_QUERY_GATEWAY_TIMEOUT_SECONDS = 30


class QueryGatewayError(RuntimeError):
    """Raised when the SQL query gateway rejects or cannot complete a request."""


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class QueryGatewayConfig:
    base_url: str = DEFAULT_QUERY_GATEWAY_BASE_URL
    api_key: str = field(default="", repr=False)
    server: str = DEFAULT_QUERY_GATEWAY_SERVER
    database: str = DEFAULT_QUERY_GATEWAY_DATABASE
    timeout_seconds: int = DEFAULT_QUERY_GATEWAY_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, load_dotenv_file: bool = True) -> "QueryGatewayConfig":
        if load_dotenv_file:
            try:
                from app.core.config import load_dotenv

                load_dotenv()
            except Exception:
                pass
        return cls(
            base_url=(
                _env_first("AUTO_KEY_IN_QUERY_GATEWAY_BASE_URL", "QUERY_GATEWAY_BASE_URL")
                or DEFAULT_QUERY_GATEWAY_BASE_URL
            ),
            api_key=(
                _env_first("AUTO_KEY_IN_QUERY_GATEWAY_API_KEY", "QUERY_GATEWAY_API_KEY")
                or ""
            ),
            server=(
                _env_first("AUTO_KEY_IN_QUERY_GATEWAY_SERVER", "QUERY_GATEWAY_SERVER")
                or DEFAULT_QUERY_GATEWAY_SERVER
            ).upper(),
            database=(
                _env_first("AUTO_KEY_IN_QUERY_GATEWAY_DATABASE", "QUERY_GATEWAY_DATABASE")
                or DEFAULT_QUERY_GATEWAY_DATABASE
            ),
            timeout_seconds=_env_int(
                "AUTO_KEY_IN_QUERY_GATEWAY_TIMEOUT_SECONDS",
                _env_int("QUERY_GATEWAY_TIMEOUT_SECONDS", DEFAULT_QUERY_GATEWAY_TIMEOUT_SECONDS),
            ),
        )

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


@dataclass(frozen=True)
class QueryGatewayResult:
    server: str
    database: str
    recordset: list[dict[str, Any]]
    rows_affected: list[int]
    execution_ms: float
    raw: dict[str, Any] = field(repr=False)


class PlantwareDbPtrjGateway:
    """HTTP client for Query Gateway calls targeting Plantware server 2 db_ptrj."""

    def __init__(
        self,
        config: QueryGatewayConfig | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or QueryGatewayConfig.from_env()
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "PlantwareDbPtrjGateway":
        return cls(QueryGatewayConfig.from_env())

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health", auth=False)
        if not isinstance(payload, dict):
            raise QueryGatewayError("Query gateway health returned invalid payload shape")
        return payload

    def list_servers(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v1/servers")
        data = payload.get("data") if isinstance(payload, dict) else None
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list):
            raise QueryGatewayError("Query gateway /v1/servers returned invalid payload shape")
        return [server for server in servers if isinstance(server, dict)]

    def list_databases(self, server: str | None = None) -> list[str]:
        target_server = (server or self.config.server).upper()
        payload = self._request("GET", "/v1/databases", params={"server": target_server})
        data = payload.get("data") if isinstance(payload, dict) else None
        databases = data.get("databases") if isinstance(data, dict) else None
        if not isinstance(databases, list):
            raise QueryGatewayError("Query gateway /v1/databases returned invalid payload shape")
        return [str(database) for database in databases]

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        database: str | None = None,
        server: str | None = None,
    ) -> QueryGatewayResult:
        sql_text = sql.strip()
        if not sql_text:
            raise QueryGatewayError("SQL query must not be empty")

        target_server = (server or self.config.server).upper()
        target_database = database or self.config.database
        body: dict[str, Any] = {
            "sql": sql_text,
            "server": target_server,
            "database": target_database,
        }
        if params:
            body["params"] = dict(params)

        payload = self._request("POST", "/v1/query", json_body=body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise QueryGatewayError("Query gateway /v1/query returned invalid data shape")

        recordset = data.get("recordset", [])
        rows_affected = data.get("rowsAffected", [])
        if not isinstance(recordset, list):
            raise QueryGatewayError("Query gateway /v1/query returned invalid recordset shape")
        if not isinstance(rows_affected, list):
            raise QueryGatewayError("Query gateway /v1/query returned invalid rowsAffected shape")

        return QueryGatewayResult(
            server=str(payload.get("server") or target_server),
            database=str(payload.get("db") or target_database),
            recordset=[row for row in recordset if isinstance(row, dict)],
            rows_affected=[int(value) for value in rows_affected if isinstance(value, int)],
            execution_ms=float(payload.get("execution_ms") or 0),
            raw=payload,
        )

    def fetch_all(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        database: str | None = None,
        server: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.execute(sql, params=params, database=database, server=server).recordset

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if auth:
            if not self.config.api_key:
                raise QueryGatewayError(
                    "Query gateway API key is required. Set AUTO_KEY_IN_QUERY_GATEWAY_API_KEY."
                )
            headers["x-api-key"] = self.config.api_key
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        url = f"{self.config.normalized_base_url()}{path}"
        try:
            response = self.session.request(
                method,
                url,
                params=dict(params) if params else None,
                json=dict(json_body) if json_body is not None else None,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise QueryGatewayError(f"Query gateway request failed: {exc}") from exc
        except ValueError as exc:
            raise QueryGatewayError("Query gateway returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise QueryGatewayError("Query gateway returned invalid payload shape")
        if payload.get("success") is False:
            message = payload.get("error") or "Query gateway returned success=false"
            raise QueryGatewayError(str(message))
        return payload
