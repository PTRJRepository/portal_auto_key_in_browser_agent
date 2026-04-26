from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import json
import shlex
import subprocess
import tempfile
from typing import Any

from app.core.config import PROJECT_ROOT
from app.core.models import RunPayload


@dataclass(frozen=True)
class RunnerEvent:
    event: str
    payload: dict[str, Any]


class RunnerBridge:
    def __init__(self, command: str) -> None:
        self.command = command
        self.process: subprocess.Popen[str] | None = None

    def run(self, payload: RunPayload, on_event: Callable[[RunnerEvent], None]) -> dict[str, Any] | None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload.to_json_dict(), handle, ensure_ascii=False)
            payload_path = Path(handle.name)

        try:
            args = [*shlex.split(self.command), "--payload", str(payload_path)]
            self.process = subprocess.Popen(
                args,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            final_result: dict[str, Any] | None = None
            assert self.process.stdout is not None
            for line in self.process.stdout:
                event = self._parse_event(line)
                if event is None:
                    on_event(RunnerEvent("log", {"message": line.rstrip()}))
                    continue
                on_event(event)
                if event.event == "result":
                    result = event.payload.get("result")
                    if isinstance(result, dict):
                        final_result = result
            exit_code = self.process.wait()
            if exit_code != 0 and final_result is None:
                raise RuntimeError(f"Runner exited with code {exit_code}")
            return final_result
        finally:
            payload_path.unlink(missing_ok=True)
            self.process = None

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def _parse_event(self, line: str) -> RunnerEvent | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        event = str(payload.get("event") or "log")
        return RunnerEvent(event, payload)
