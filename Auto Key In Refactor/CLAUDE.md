# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

Run the desktop app from this directory:

```bash
python -m app
```

Install Python dependencies for development:

```bash
pip install -e .[dev]
```

Run the Python test suite:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -v
```

Run a single Python test:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api_models.py::test_scan_session_status_detects_active_division_session -v
```

Install runner dependencies:

```bash
npm --prefix runner install
```

Build the TypeScript Playwright runner:

```bash
npm --prefix runner run build
```

Run the built runner directly with a payload:

```bash
node runner/dist/cli.js --payload data/cache/dry-run-payload.json
```

Run the TypeScript runner in dev mode:

```bash
npm --prefix runner run dev -- --payload data/cache/dry-run-payload.json
```

Install Playwright Chromium for the runner:

```bash
npx --prefix runner playwright install chromium
```

Windows setup scripts exist for fresh environments:

```bash
powershell -ExecutionPolicy Bypass -File ./setup.ps1
bash setup.sh
```

## Architecture Overview

This project is a desktop controller for PlantwareP3 manual adjustment auto key-in. It has two main parts:

- `app/`: Python PySide6 desktop UI and orchestration layer.
- `runner/`: TypeScript Playwright automation that performs the browser key-in work.

The Python UI starts at `app/main.py`, which loads app config, adjustment categories, and division options before constructing `app.ui.main_window.MainWindow`.

`MainWindow` owns most UI behavior: config controls, session status, data fetch, process tables, run event handling, summary, and db_ptrj verification. It uses Qt worker objects moved to `QThread` for API fetches, runner execution, session refresh, and verification.

Core Python modules are intentionally small:

- `app/core/config.py`: loads `.env`, app defaults, and `configs/divisions.json` into `AppConfig` and `DivisionOption`.
- `app/core/category_registry.py`: loads `configs/adjustment-categories.json` and detects category keys from adjustment names/types.
- `app/core/api_client.py`: calls Manual Adjustment API endpoints and normalizes records.
- `app/core/models.py`: dataclasses for `ManualAdjustmentRecord` and `RunPayload`.
- `app/core/runner_bridge.py`: serializes a `RunPayload`, spawns `node runner/dist/cli.js --payload <temp-json>`, and streams JSON events back to the UI.
- `app/core/run_artifacts.py`: stores payload/result/events under `data/runs/`.

The runner is a Node/TypeScript CLI. `runner/src/cli.ts` routes by `runner_mode` to dry-run, mock, session management, or the main multi-tab Playwright runner. The default real automation path uses `runner/src/orchestration/multi-tab-runner.ts`, which creates a `BrowserSession`, opens multiple tabs, processes assigned rows, and emits line-delimited JSON events to stdout for Python to consume.

Sessions are saved per division as `runner/data/sessions/session-<DIVISION>.json`. The UI treats a session as active when the saved division matches and its age is under 240 minutes. Real runs for session-reuse modes should use the same division code in the payload and session file.

## Local Configuration and Generated Files

Runtime configuration comes primarily from `.env`; `configs/app.json` is local override data and may contain secrets. Do not rely on committed values for credentials.

Local/generated paths include:

- `.env`
- `configs/app.json`
- `data/runs/`
- `runner/data/sessions/*.json`
- `runner/dist/`
- `runner/node_modules/`
- `__pycache__/` and `.pytest_cache/`

## Worktree Preference

For isolated implementation work, use the project-local `.worktrees/` directory at the repository root when possible. Ensure the directory remains ignored by git before creating worktrees there.
