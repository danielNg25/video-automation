.PHONY: install install-linux setup test lint format check clean docker-up docker-down docker-build docker-rebuild docker-build-nocache docker-logs api ui

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

# One-time bootstrap: seed local config files from their .example templates so
# bind-mounted paths exist before `docker compose up`. Idempotent — won't
# overwrite a config you've already filled in.
setup:
	@if [ ! -f config/config.yaml ]; then \
		cp config/config.example.yaml config/config.yaml; \
		echo "Created config/config.yaml from example."; \
	fi
	@if [ ! -f config/douyin_web_config.yaml ]; then \
		cp config/douyin_web_config.example.yaml config/douyin_web_config.yaml; \
		echo "Created config/douyin_web_config.yaml from example."; \
		echo "  → Edit it and replace PASTE_YOUR_DOUYIN_COOKIE_HERE with a real"; \
		echo "    Cookie header to enable the primary Douyin API path."; \
		echo "    (Without a real cookie, downloads fall back to yt-dlp.)"; \
	fi

# Docker (full stack: douyin-api + app). Runs setup first so the bind-mount
# sources exist — important on fresh clones (especially Windows/WSL2, where a
# missing bind-mount source auto-creates as a directory and breaks the mount).
docker-up: setup
	docker compose up -d --build

docker-down:
	docker compose down

# Build the app image (incremental, uses Docker layer cache + pip wheel cache).
# Fast for code changes; even when pyproject.toml changes, pip reuses cached wheels.
docker-build:
	docker compose build app

# Build + restart the app container (incremental). Use this after code changes.
docker-rebuild: setup
	docker compose build app
	docker compose up -d --force-recreate app

# Nuclear option: wipe Docker layer cache and rebuild from scratch.
# Avoid unless you suspect a stale layer is the actual problem — re-downloads ~200MB of paddlepaddle.
docker-build-nocache:
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
