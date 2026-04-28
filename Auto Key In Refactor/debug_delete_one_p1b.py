from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    payload = {
        "period_month": 4,
        "period_year": 2026,
        "division_code": "P1B",
        "gang_code": None,
        "emp_code": None,
        "adjustment_type": "AUTO_BUFFER",
        "adjustment_name": "AUTO SPSI",
        "category_key": "spsi",
        "runner_mode": "session_reuse_single",
        "max_tabs": 1,
        "headless": False,
        "only_missing_rows": True,
        "row_limit": None,
        "records": [],
        "operation": "delete_duplicates",
        "delete_dry_run": False,
        "duplicate_targets": [{
            "master_id": "674281",
            "doc_id": "ADP1B26041047",
            "doc_date": "2026-04-25",
            "emp_code": "B0001",
            "emp_name": "ALI SUDIANTO ( RAHIMA",
            "doc_desc": "POTONGAN SPSI",
            "amount": 4000,
            "action": "DELETE_OLD",
            "keep_doc_id": "ADP1B26041145",
            "category": "spsi",
            "raw": {"id": "674281", "doc_id": "ADP1B26041047", "action": "DELETE_OLD"},
        }],
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        payload_path = Path(handle.name)
    try:
        command = ["node", "runner/dist/cli.js", "--payload", str(payload_path)]
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        assert process.stdout is not None
        for line in process.stdout:
            print(line.rstrip())
        return process.wait()
    finally:
        payload_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
