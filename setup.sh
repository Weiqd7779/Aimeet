#!/usr/bin/env bash
# One-shot local setup: installs uv if needed, syncs api/web dependencies,
# and creates api/.env from .env.example. Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js 20+ is required (https://nodejs.org)" >&2
  exit 1
fi

echo "==> api dependencies"
(cd api && uv sync)

echo "==> web dependencies"
(cd web && npm install)

if [ ! -f api/.env ]; then
  cp .env.example api/.env
  echo "==> created api/.env from .env.example"
  echo "    fill in OPENAI_API_KEY and set MOCK_MODE=false for real Google Meet testing"
fi

echo "==> done. run 'make dev' to start api (:8000) and web (:3000)"
