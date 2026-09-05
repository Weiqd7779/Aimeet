.PHONY: setup dev dev-web dev-api restart e2e lint test

setup:
	./setup.sh

dev: setup
	($(MAKE) dev-api & $(MAKE) dev-web & wait)

# Both dev targets go through dev.ps1: it kills whatever still holds the port (and, for the
# API, any orphaned uvicorn worker of this checkout) before starting, and kills the tree it
# started when you Ctrl+C. Never start uvicorn / next directly on Windows.
dev-web:
	cd web && powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1

dev-api:
	cd api && powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1

# Kill everything on :8000 / :3000 without starting anything.
restart:
	powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { taskkill /PID $$_ /T /F }"

e2e:
	cd api && uv run python -m e2e.run $(SCENARIOS)

lint:
	cd web && npm run lint
	cd api && uv run ruff check .

test:
	cd api && uv run pytest -q
