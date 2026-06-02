"""Data models for AUTO_BUFFER comparison between extend_db_ptrj and db_ptrj.

These dataclasses replicate the structures returned by Daftar Upah's
``reverseCompareAdtransWithAdjustments`` service so the Auto Key In app
can produce equivalent results without depending on the API.

Status semantics (matching Daftar Upah):

- ``MATCH`` — stored amount in ``extend_db_ptrj.payroll_manual_adjustments``
  equals the summed amount from ``db_ptrj.PR_ADTRANS`` (within 0.01).
- ``MISMATCH`` — both sides have a value but they differ. User-facing label: DIFF.
- ``EXTRA_IN_ADJUSTMENTS`` — value exists only in ``extend_db_ptrj``;
  ``db_ptrj`` has no matching row (source amount == 0). User-facing label: MISS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ComparisonStatus = Literal["MATCH", "MISMATCH", "EXTRA_IN_ADJUSTMENTS"]

# Adjustment names that are considered AUTO_BUFFER comparable in Auto Key In.
AUTO_BUFFER_COMPARABLE_NAMES: tuple[str, ...] = (
    "TUNJANGAN JABATAN",
    "MASA KERJA",
    "SPSI",
    "POTONGAN PPH",
    "PREMI",
)

# Map between Auto Key In category_key and the canonical adjustment_name in extend_db_ptrj.
CATEGORY_TO_ADJUSTMENT_NAME: dict[str, str] = {
    "tunjangan_jabatan": "TUNJANGAN JABATAN",
    "masa_kerja": "MASA KERJA",
    "spsi": "SPSI",
    "pph21": "POTONGAN PPH",
    "premi": "PREMI",
}

ADJUSTMENT_NAME_TO_CATEGORY: dict[str, str] = {
    name: category for category, name in CATEGORY_TO_ADJUSTMENT_NAME.items()
}


@dataclass(frozen=True)
class StoredAdjustment:
    """A row from ``extend_db_ptrj.dbo.payroll_manual_adjustments`` filtered to AUTO_BUFFER."""

    emp_code: str
    nik: str
    adjustment_type: str
    adjustment_name: str
    amount: float
    remarks: str
    gang_code: str
    division_code: str


@dataclass(frozen=True)
class AdtransTotal:
    """A summed amount from ``db_ptrj.PR_ADTRANS`` (and PR_ADTRANS_ARC) for a single
    employee + comparison category.
    """

    emp_code: str
    category: str
    amount: float


@dataclass(frozen=True)
class ComparisonItem:
    """Pairwise comparison result for a single (emp_code, category)."""

    emp_code: str
    category: str
    adjustment_name: str
    stored_amount: float
    source_amount: float
    diff: float
    status: ComparisonStatus
    gang_code: str = ""
    division_code: str = ""
    remarks: str = ""
    stored_emp_identifier: str = ""

    @property
    def is_miss(self) -> bool:
        return self.status == "EXTRA_IN_ADJUSTMENTS"

    @property
    def is_diff(self) -> bool:
        return self.status == "MISMATCH"


@dataclass(frozen=True)
class ComparisonResult:
    """Full comparison output for one (division, period_month, period_year)."""

    division: str
    period_month: int
    period_year: int
    comparisons: tuple[ComparisonItem, ...] = field(default_factory=tuple)
    match_count: int = 0
    mismatch_count: int = 0
    extra_count: int = 0

    @property
    def total(self) -> int:
        return len(self.comparisons)

    @property
    def miss_and_diff(self) -> tuple[ComparisonItem, ...]:
        """Items that need to be auto-keyed-in: DIFF or MISS."""
        return tuple(item for item in self.comparisons if item.status != "MATCH")


def normalize_auto_buffer_adjustment_name(value: str) -> str:
    """Strip optional "AUTO " prefix and normalize whitespace/case.

    Replicates Daftar Upah's ``normalizeAutoBufferAdjustmentName`` so that
    e.g. "AUTO TUNJANGAN JABATAN" maps back to "TUNJANGAN JABATAN".
    """
    if not value:
        return ""
    upper = " ".join(value.upper().split())
    if upper.startswith("AUTO "):
        upper = upper[len("AUTO "):].strip()
    return upper
