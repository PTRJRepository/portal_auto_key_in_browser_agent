from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from app.core.models import DuplicateDocIdTarget
from app.core.query_gateway import PlantwareDbPtrjGateway

LOOSEFRUIT_DUPLICATE_CATEGORY = "loosefruit"
LOOSEFRUIT_DUPLICATE_SOURCE = "loosefruit-pr-loosefruit"


@dataclass(frozen=True)
class LoosefruitDuplicateDocId:
    id: int | None
    doc_id: str
    doc_date: str
    doc_desc: str
    loc_code: str
    acc_month: int | None
    acc_year: int | None
    phy_month: int | None
    phy_year: int | None
    status: str
    auto_cal_mt: float | None
    total_mt: float | None
    raw: dict[str, Any]

    def to_duplicate_target(self) -> DuplicateDocIdTarget:
        return DuplicateDocIdTarget(
            master_id=str(self.id or ""),
            doc_id=self.doc_id,
            doc_date=self.doc_date,
            emp_code="",
            emp_name="",
            doc_desc=self.doc_desc or "LOOSEFRUIT",
            amount=self.total_mt,
            action="DELETE_RECORD",
            keep_doc_id="",
            category=LOOSEFRUIT_DUPLICATE_CATEGORY,
            raw={
                "source": LOOSEFRUIT_DUPLICATE_SOURCE,
                "table": "db_ptrj.dbo.PR_LOOSEFRUIT",
                "id": self.id,
                "doc_id": self.doc_id,
                "doc_desc": self.doc_desc,
                "loc_code": self.loc_code,
                "status": self.status,
                "acc_month": self.acc_month,
                "acc_year": self.acc_year,
                "phy_month": self.phy_month,
                "phy_year": self.phy_year,
                "auto_cal_mt": self.auto_cal_mt,
                "total_mt": self.total_mt,
                "action": "DELETE_RECORD",
                "raw": self.raw,
            },
        )


class LoosefruitGatewayRepository:
    """Reads duplicate Loosefruit DocIDs through Query Gateway only."""

    def __init__(self, gateway: PlantwareDbPtrjGateway | None = None) -> None:
        self.gateway = gateway or PlantwareDbPtrjGateway.from_env()

    def list_duplicate_doc_ids(
        self,
        loc_code: str | None = None,
        acc_month: int | None = None,
        acc_year: int | None = None,
        phy_month: int | None = None,
        phy_year: int | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[LoosefruitDuplicateDocId]:
        safe_limit = max(1, min(int(limit), 10000))
        sql, params = self._build_duplicate_doc_ids_query(
            loc_code=loc_code,
            acc_month=acc_month,
            acc_year=acc_year,
            phy_month=phy_month,
            phy_year=phy_year,
            status=status,
            limit=safe_limit,
        )
        rows = self.gateway.fetch_all(sql, params=params)
        return [normalize_loosefruit_duplicate_row(row) for row in rows]

    def list_duplicate_targets(
        self,
        loc_code: str | None = None,
        acc_month: int | None = None,
        acc_year: int | None = None,
        phy_month: int | None = None,
        phy_year: int | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[DuplicateDocIdTarget]:
        return [
            row.to_duplicate_target()
            for row in self.list_duplicate_doc_ids(
                loc_code=loc_code,
                acc_month=acc_month,
                acc_year=acc_year,
                phy_month=phy_month,
                phy_year=phy_year,
                status=status,
                limit=limit,
            )
        ]

    def _build_duplicate_doc_ids_query(
        self,
        loc_code: str | None,
        acc_month: int | None,
        acc_year: int | None,
        phy_month: int | None,
        phy_year: int | None,
        status: str | None,
        limit: int,
    ) -> tuple[str, dict[str, Any]]:
        where = ["[DocID] LIKE @docIdPattern ESCAPE '\\'"]
        params: dict[str, Any] = {"docIdPattern": "%\\_%"}
        if loc_code and loc_code.strip():
            where.append("[LocCode] = @locCode")
            params["locCode"] = loc_code.strip().upper()
        if acc_month and acc_month > 0:
            where.append("[AccMonth] = @accMonth")
            params["accMonth"] = int(acc_month)
        if acc_year and acc_year > 0:
            where.append("[AccYear] = @accYear")
            params["accYear"] = int(acc_year)
        if phy_month and phy_month > 0:
            where.append("[PhyMonth] = @phyMonth")
            params["phyMonth"] = int(phy_month)
        if phy_year and phy_year > 0:
            where.append("[PhyYear] = @phyYear")
            params["phyYear"] = int(phy_year)
        if status and status.strip():
            where.append("[Status] = @status")
            params["status"] = status.strip()

        sql = f"""
SELECT TOP ({limit})
    [ID],
    [DocID],
    [DocDate],
    [DocDesc],
    [LocCode],
    [AccMonth],
    [AccYear],
    [PhyMonth],
    [PhyYear],
    [Status],
    [CreatedBy],
    [CreatedDate],
    [UpdatedBy],
    [UpdatedDate],
    [ImpFlag],
    [AutoCalMT],
    [TotalMT]
FROM [dbo].[PR_LOOSEFRUIT]
WHERE {' AND '.join(where)}
""".strip()
        return sql, params


def normalize_loosefruit_duplicate_row(row: Mapping[str, Any]) -> LoosefruitDuplicateDocId:
    raw = dict(row)
    return LoosefruitDuplicateDocId(
        id=_int_or_none(_first(raw, "ID", "id")),
        doc_id=_text(raw, "DocID", "doc_id", "docId"),
        doc_date=_date_text(_first(raw, "DocDate", "doc_date", "docDate")),
        doc_desc=_text(raw, "DocDesc", "doc_desc", "docDesc"),
        loc_code=_text(raw, "LocCode", "loc_code", "locCode").upper(),
        acc_month=_int_or_none(_first(raw, "AccMonth", "acc_month", "accMonth")),
        acc_year=_int_or_none(_first(raw, "AccYear", "acc_year", "accYear")),
        phy_month=_int_or_none(_first(raw, "PhyMonth", "phy_month", "phyMonth")),
        phy_year=_int_or_none(_first(raw, "PhyYear", "phy_year", "phyYear")),
        status=_text(raw, "Status", "status"),
        auto_cal_mt=_float_or_none(_first(raw, "AutoCalMT", "auto_cal_mt", "autoCalMt")),
        total_mt=_float_or_none(_first(raw, "TotalMT", "total_mt", "totalMt")),
        raw=raw,
    )


def _first(raw: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


def _text(raw: Mapping[str, Any], *names: str) -> str:
    value = _first(raw, *names)
    return "" if value is None else str(value).strip()


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if "T" in text:
        return text.split("T", 1)[0]
    if " " in text:
        return text.split(" ", 1)[0]
    return text
