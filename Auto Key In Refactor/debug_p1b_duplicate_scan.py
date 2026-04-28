from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.api_client import ManualAdjustmentApiClient
from app.core.category_registry import CategoryRegistry
from app.core.config import load_app_config


def main() -> int:
    config = load_app_config()
    division = "P1B"
    filters = ["spsi"]
    client = ManualAdjustmentApiClient(config.api_base_url, config.api_key, CategoryRegistry([]), timeout_seconds=60)
    targets = client.get_duplicate_delete_targets(config.default_period_month, config.default_period_year, division, filters)
    print(json.dumps({"event": "debug.fetch.completed", "division_code": division, "filters": filters, "target_count": len(targets)}, ensure_ascii=False))

    payload = {
        "period_month": config.default_period_month,
        "period_year": config.default_period_year,
        "division_code": division,
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
        "operation": "debug_duplicate_scan",
        "duplicate_targets": [target.to_runner_dict() for target in targets],
        "delete_dry_run": True,
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
