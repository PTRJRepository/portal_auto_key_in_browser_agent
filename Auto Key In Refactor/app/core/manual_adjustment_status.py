from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


MISSING_SYNC_STATUSES = {"MISS", "MISSING", "NOT_FOUND"}
MISMATCH_STATUSES = {"MISMATCH", "DIFF", "PARTIAL", "VERIFIED_MISMATCH"}
SYNCED_STATUSES = {"SYNC", "MATCH", "VERIFIED_MATCH"}


class HasRemarksAmount(Protocol):
    remarks: str
    amount: float


@dataclass(frozen=True)
class RemarksStatus:
    sync_status: str
    match_status: str

    @property
    def is_synced(self) -> bool:
        return self.sync_status == "SYNC" and self.match_status in {"MATCH", "SYNC"}

    @property
    def is_missing(self) -> bool:
        return self.sync_status in MISSING_SYNC_STATUSES

    @property
    def is_mismatch(self) -> bool:
        return self.match_status in MISMATCH_STATUSES or self.sync_status in {"DIFF", "PARTIAL"}

    @property
    def input_needed(self) -> bool:
        return self.is_missing or self.is_mismatch


def remarks_parts(remarks: str) -> list[str]:
    return [part.strip() for part in (remarks or "").split("|") if part.strip()]


def remarks_token(remarks: str, key: str) -> str:
    prefix = f"{key.lower()}:"
    for part in remarks_parts(remarks):
        if part.lower().startswith(prefix):
            return part.split(":", 1)[1].strip().upper()
    return ""


def status_from_record(record: HasRemarksAmount) -> RemarksStatus:
    sync_status = sync_status_from_remarks(record)
    match_status = match_status_from_remarks(record)
    return RemarksStatus(sync_status, match_status)


def sync_status_from_remarks(record: HasRemarksAmount) -> str:
    explicit_sync = remarks_token(record.remarks, "sync")
    if explicit_sync:
        return explicit_sync
    parts = remarks_parts(record.remarks)
    if len(parts) >= 3:
        amount_part = parts[2].replace(",", "")
        try:
            remarks_amount = float(amount_part)
        except ValueError:
            return "UNKNOWN"
        return "MATCH" if remarks_amount == record.amount else "MISMATCH"
    if record.remarks.strip():
        return "MANUAL"
    return "NO REMARKS"


def match_status_from_remarks(record: HasRemarksAmount) -> str:
    explicit_match = remarks_token(record.remarks, "match")
    if explicit_match:
        return explicit_match
    return sync_status_from_remarks(record)


def is_synced_from_remarks(record: HasRemarksAmount) -> bool:
    return status_from_record(record).is_synced


def is_missing_from_remarks(record: HasRemarksAmount) -> bool:
    return status_from_record(record).is_missing


def is_mismatch_from_remarks(record: HasRemarksAmount) -> bool:
    return status_from_record(record).is_mismatch


def input_needed_from_remarks(record: HasRemarksAmount) -> bool:
    return status_from_record(record).input_needed
