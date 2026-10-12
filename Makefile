.PHONY: up down setup api ui test lint eval audit redteam

up:            ## Everything in Docker: UI :3000, API :8000
	docker compose up --build

down:
	docker compose down

setup:         ## Local development without Docker (SQLite)
	python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

api:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

ui:
	cd frontend && npm run dev

test:
	cd backend && ../.venv/bin/python -m pytest --cov=app --cov-report=term-missing:skip-covered
	cd sample_app && ../.venv/bin/python -m pytest -q

lint:
	cd backend && ../.venv/bin/python -m ruff check app tests

eval:          ## AI evaluation gate (score must be above 80)
	cd backend && ../.venv/bin/python -m app.cli evaluate --min-score 80

audit:         ## Capability and escape-path audit of the committed policies
	cd backend && ../.venv/bin/python -m app.cli audit-capabilities

redteam:       ## Safe red-team suite against mocks
	cd backend && LAB_DATA_DIR=$$(mktemp -d) ../.venv/bin/python -m app.cli red-team
