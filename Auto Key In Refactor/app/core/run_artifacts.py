from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
from typing import Any

from app.core.config import PROJECT_ROOT
from app.core.models import RunPayload


@dataclass(frozen=True)
class RunArtifactPaths:
    run_id: str
    directory: Path
    payload_path: Path
    result_path: Path
    events_path: Path


class RunArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or PROJECT_ROOT / "data" / "runs"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, payload: RunPayload) -> RunArtifactPaths:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{timestamp}-{payload.category_key}-{payload.runner_mode}"
        directory = self.root / run_id
        directory.mkdir(parents=True, exist_ok=False)
        paths = RunArtifactPaths(
            run_id=run_id,
            directory=directory,
            payload_path=directory / "payload.json",
            result_path=directory / "result.json",
            events_path=directory / "events.ndjson",
        )
        self.write_payload(paths, payload)
        return paths

    def write_payload(self, paths: RunArtifactPaths, payload: RunPayload) -> None:
        paths.payload_path.write_text(json.dumps(payload.to_json_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def append_event(self, paths: RunArtifactPaths, event: dict[str, Any]) -> None:
        with paths.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_result(self, paths: RunArtifactPaths, result: dict[str, Any] | None) -> None:
        paths.result_path.write_text(json.dumps(result or {}, indent=2, ensure_ascii=False), encoding="utf-8")
