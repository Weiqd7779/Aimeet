.PHONY: dev-web dev-api e2e lint

dev-web:
	cd web && npm run dev

dev-api:
	cd api && uv run uvicorn app.main:app --reload --reload-dir app

e2e:
	cd api && uv run python -m e2e.run $(SCENARIOS)

lint:
	cd web && npm run lint
	cd api && uv run ruff check .
