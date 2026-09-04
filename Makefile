.PHONY: setup dev dev-web dev-api e2e lint test

setup:
	./setup.sh

dev: setup
	($(MAKE) dev-api & $(MAKE) dev-web & wait)

dev-web:
	cd web && npm run dev

dev-api:
	cd api && uv run uvicorn app.main:app --reload --reload-dir app

e2e:
	cd api && uv run python -m e2e.run $(SCENARIOS)

lint:
	cd web && npm run lint
	cd api && uv run ruff check .

test:
	cd api && uv run pytest -q
