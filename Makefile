.PHONY: dev-web dev-api lint

dev-web:
	cd web && npm run dev

dev-api:
	cd api && uv run uvicorn app.main:app --reload

lint:
	cd web && npm run lint
	cd api && uv run ruff check .
