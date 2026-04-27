$ErrorActionPreference = "Stop"

Write-Host "== Auto Key In Refactor setup =="

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Edit .env before running the app."
}

python -m pip install -e ".[dev]"
npm --prefix runner install
npm --prefix runner run build
npx --prefix runner playwright install chromium

Write-Host "Setup complete. Edit .env, then run: python -m app"
