from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"


@dataclass(frozen=True)
class AppConfig:
    api_base_url: str = "http://localhost:8002"
    api_key: str = ""
    runner_command: str = "node runner/dist/cli.js"
    default_period_month: int = 4
    default_period_year: int = 2026
    default_division_code: str = "P1B"
    default_runner_mode: str = "multi_tab_shared_session"
    default_max_tabs: int = 5
    headless: bool = False


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_DIR / "app.json"
    example_path = CONFIG_DIR / "app.example.json"
    data: dict[str, object] = {}

    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    elif example_path.exists():
        data = json.loads(example_path.read_text(encoding="utf-8"))

    api_key = str(data.get("api_key") or os.getenv("AUTO_KEY_IN_API_KEY", ""))

    return AppConfig(
        api_base_url=str(data.get("api_base_url", "http://localhost:8002")).rstrip("/"),
        api_key=api_key,
        runner_command=str(data.get("runner_command", "node runner/dist/cli.js")),
        default_period_month=int(data.get("default_period_month", 4)),
        default_period_year=int(data.get("default_period_year", 2026)),
        default_division_code=str(data.get("default_division_code", "P1B")),
        default_runner_mode=str(data.get("default_runner_mode", "multi_tab_shared_session")),
        default_max_tabs=int(data.get("default_max_tabs", 5)),
        headless=bool(data.get("headless", False)),
    )
