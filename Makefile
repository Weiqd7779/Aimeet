.PHONY: dev-web dev-api e2e lint

dev-web:
	cd web && npm run dev

dev-api:
	cd api && powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1

e2e:
	cd api && uv run python -m e2e.run $(SCENARIOS)

lint:
	cd web && npm run lint
	cd api && uv run ruff check .
