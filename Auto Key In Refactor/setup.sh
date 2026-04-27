#!/usr/bin/env bash
set -euo pipefail

echo "== Auto Key In Refactor setup =="

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit .env before running the app."
fi

python -m pip install -e ".[dev]"
npm --prefix runner install
npm --prefix runner run build
npx --prefix runner playwright install chromium

echo "Setup complete. Edit .env, then run: python -m app"
