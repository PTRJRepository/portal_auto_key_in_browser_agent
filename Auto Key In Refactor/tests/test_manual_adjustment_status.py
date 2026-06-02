from types import SimpleNamespace

from app.core.manual_adjustment_status import (
    input_needed_from_remarks,
    is_missing_from_remarks,
    is_mismatch_from_remarks,
    is_synced_from_remarks,
    match_status_from_remarks,
    sync_status_from_remarks,
)


def record(remarks: str, amount: float = 0) -> SimpleNamespace:
    return SimpleNamespace(remarks=remarks, amount=amount)


def test_koreksi_panen_miss_mismatch_requires_input():
    item = record(
        "KOREKSI PANEN | (DE0004AB1) (DE) POTONGAN PREMI - (DE) POTONGAN PREMI | 88172 | sync:MISS | match:MISMATCH",
        88172,
    )

    assert sync_status_from_remarks(item) == "MISS"
    assert match_status_from_remarks(item) == "MISMATCH"
    assert is_missing_from_remarks(item)
    assert is_mismatch_from_remarks(item)
    assert input_needed_from_remarks(item)


def test_synced_match_does_not_require_input():
    item = record("PREMI TIKET | (AL) TUNJANGAN PREMI | 50000 | sync:SYNC | match:MATCH", 50000)

    assert is_synced_from_remarks(item)
    assert not is_missing_from_remarks(item)
    assert not is_mismatch_from_remarks(item)
    assert not input_needed_from_remarks(item)


def test_diff_status_requires_input():
    item = record("PREMI ANGKUT PUPUK | (AL) TUNJANGAN PREMI | 125000 | sync:DIFF | match:MISMATCH", 125000)

    assert not is_synced_from_remarks(item)
    assert is_mismatch_from_remarks(item)
    assert input_needed_from_remarks(item)


def test_legacy_amount_fallback_still_works():
    match = record("SPSI | SPSI | 10000", 10000)
    mismatch = record("SPSI | SPSI | 10000", 9000)

    assert sync_status_from_remarks(match) == "MATCH"
    assert sync_status_from_remarks(mismatch) == "MISMATCH"
    assert match_status_from_remarks(mismatch) == "MISMATCH"
