# PDF Ingestion Layer — Development Commands
# Usage: make <target>

.PHONY: setup backend frontend dev test lint clean

# ─── Full Setup (first time) ─────────────────────────────────────────────────

setup: setup-backend setup-frontend
	@echo "✓ Setup complete. Run 'make dev' to start."

setup-backend:
	@echo "→ Setting up Python backend..."
	cd pdf_ingestion && python -m venv .venv
	cd pdf_ingestion && .venv/bin/pip install --upgrade pip
	cd pdf_ingestion && .venv/bin/pip install -e ".[dev]"
	@if [ ! -f pdf_ingestion/.env ]; then \
		cp pdf_ingestion/.env.example pdf_ingestion/.env; \
		echo "→ Created .env from template. Edit pdf_ingestion/.env with your AWS credentials."; \
	fi

setup-frontend:
	@echo "→ Setting up React frontend..."
	cd pdf_ingestion/frontend && npm install

# ─── Development ─────────────────────────────────────────────────────────────

# AWS profile for Bedrock VLM calls. Override: make backend AWS_PROFILE=other
AWS_PROFILE ?= smartstream

backend:
	cd pdf_ingestion && AWS_PROFILE=$(AWS_PROFILE) .venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	cd pdf_ingestion/frontend && npm run dev

dev:
	@echo "Start backend and frontend in separate terminals:"
	@echo "  Terminal 1: make backend"
	@echo "  Terminal 2: make frontend"
	@echo ""
	@echo "Or use: make dev-parallel (requires 'concurrently' or run in background)"

# ─── Testing ─────────────────────────────────────────────────────────────────

test: test-backend test-frontend

test-backend:
	cd pdf_ingestion && .venv/bin/python -m pytest tests/ -q --tb=short

test-frontend:
	cd pdf_ingestion/frontend && npm test

# ─── Linting & Formatting ────────────────────────────────────────────────────

lint:
	cd pdf_ingestion && .venv/bin/ruff check .
	cd pdf_ingestion && .venv/bin/ruff format --check .

format:
	cd pdf_ingestion && .venv/bin/ruff format .

# ─── Docker ──────────────────────────────────────────────────────────────────

docker-up:
	cd pdf_ingestion && docker compose up -d

docker-down:
	cd pdf_ingestion && docker compose down

docker-logs:
	cd pdf_ingestion && docker compose logs -f api

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	rm -rf pdf_ingestion/.venv 2>/dev/null || true
