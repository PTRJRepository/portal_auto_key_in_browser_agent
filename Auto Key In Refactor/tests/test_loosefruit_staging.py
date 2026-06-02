from app.core.loosefruit_staging import (
    eligible_loosefruit_rows,
    loosefruit_staging_comparison_url,
    normalize_loosefruit_staging_payload,
)


def test_loosefruit_staging_url_accepts_full_user_route():
    url = loosefruit_staging_comparison_url("http://localhost:3001/upah/staging-comparison", "2026-05")

    assert url == "http://localhost:8002/backend/upah/api/staging/staging-comparison?periode=2026-05"


def test_loosefruit_staging_url_accepts_api_base_route():
    url = loosefruit_staging_comparison_url("http://localhost:8002", "2026-05")

    assert url == "http://localhost:8002/backend/upah/api/staging/staging-comparison?periode=2026-05"


def test_normalize_and_filter_eligible_loosefruit_rows():
    comparison = normalize_loosefruit_staging_payload(
        {
            "data": {
                "periode": "2026-05",
                "totals": {"staging_brondol": "10", "plantware_brondol": "4", "selisih": "6"},
                "rows": [
                    {"emp_code": "a0001", "estate": "p1a", "gang": "a1h", "staging_brondol": "7", "plantware_brondol": "2", "selisih": "5"},
                    {"emp_code": "A0002", "estate": "P1A", "gang": "A1H", "staging_brondol": 2, "plantware_brondol": 2, "selisih": 0},
                    {"emp_code": "B0001", "estate": "P1A", "gang": "B1H", "staging_brondol": 5, "plantware_brondol": 1, "selisih": 4},
                    {"emp_code": "A0003", "estate": "P1B", "gang": "B1H", "staging_brondol": 4, "plantware_brondol": 1, "selisih": 3},
                ],
            }
        },
        "source",
    )

    eligible = eligible_loosefruit_rows(comparison.rows, "P1A")

    assert comparison.totals.selisih == 6
    assert [row.emp_code for row in eligible] == ["A0001", "B0001"]
