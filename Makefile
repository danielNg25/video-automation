.PHONY: install install-linux test lint format check clean docker-up docker-down docker-build docker-rebuild docker-logs api ui

# Development (macOS)
install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[macos]" && pip install ruff pytest pytest-asyncio

# Production (Linux)
install-linux:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[linux]" && pip install ruff pytest pytest-asyncio

# Testing
test:
	python -m pytest tests/ -v

test-unit:
	python -m pytest tests/ -v -m "not integration"

test-integration:
	python -m pytest tests/ -v -m integration

# Linting & formatting
lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

check: lint test

# Docker (full stack: douyin-api + app)
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-build:
	docker compose build app

docker-rebuild:
	docker compose build --no-cache app

docker-logs:
	docker compose logs -f app

# API server
api:
	. .venv/bin/activate && uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# UI dev server
ui:
	cd ui-app && npm run dev

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf dist/ build/
