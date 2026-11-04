SHELL := /usr/bin/env bash
BACKEND := backend
FRONTEND := frontend
UV ?= uv
PNPM ?= pnpm
PYTHON ?= python3

.PHONY: help install install-backend install-frontend lint format typecheck test test-backend test-frontend coverage \
        contracts contracts-export contracts-check stubs lockfile-hashes testdata build build-backend build-frontend up down logs clean

help:
	@echo "Trendsmapp developer commands"
	@echo "  make install          Install backend and frontend dependencies from the lockfiles"
	@echo "  make lint             Run Ruff and ESLint"
	@echo "  make format           Format backend and frontend sources"
	@echo "  make typecheck        Run MyPy and TypeScript checks"
	@echo "  make test             Run the backend and frontend test suites"
	@echo "  make coverage         Run the backend suite with the coverage gate"
	@echo "  make contracts        Export and verify the API contract snapshot"
	@echo "  make stubs            Fail if a production path contains a prohibited placeholder"
	@echo "  make lockfile-hashes  Fail when the recorded dependency hashes are stale"
	@echo "  make build            Build the backend wheel and the frontend production bundle"
	@echo "  make up               Start PostgreSQL, the object store, the API, and the worker"
	@echo "  make down             Stop the local stack"

install: install-backend install-frontend

install-backend:
	cd $(BACKEND) && $(UV) sync --frozen --all-groups

install-frontend:
	cd $(FRONTEND) && $(PNPM) install --frozen-lockfile

lint:
	cd $(BACKEND) && $(UV) run ruff check .
	cd $(BACKEND) && $(UV) run ruff format --check .
	cd $(FRONTEND) && $(PNPM) run lint

format:
	cd $(BACKEND) && $(UV) run ruff format .
	cd $(BACKEND) && $(UV) run ruff check --fix .
	cd $(FRONTEND) && $(PNPM) run format

typecheck:
	cd $(BACKEND) && $(UV) run mypy
	cd $(FRONTEND) && $(PNPM) run typecheck

test: test-backend test-frontend

test-backend:
	cd $(BACKEND) && $(UV) run pytest -q

test-frontend:
	cd $(FRONTEND) && $(PNPM) run test

coverage:
	cd $(BACKEND) && $(UV) run pytest --cov --cov-report=term --cov-report=xml

contracts: contracts-export contracts-check

contracts-export:
	cd $(BACKEND) && $(UV) run python scripts/export_openapi.py --output ../contracts/openapi.v1.json
	cd $(BACKEND) && $(UV) run python scripts/export_schema_versions.py --output ../contracts/schema-versions.json

contracts-check:
	cd $(BACKEND) && $(UV) run python scripts/export_openapi.py --check ../contracts/openapi.v1.json
	cd $(BACKEND) && $(UV) run python scripts/export_schema_versions.py --check ../contracts/schema-versions.json
	cd $(BACKEND) && $(UV) run python ../scripts/verify_contract_examples.py
	$(UV) run --no-project python scripts/check_contract_compatibility.py
	cd $(FRONTEND) && $(PNPM) run check:api-types

stubs:
	$(UV) run --no-project python scripts/check_no_stubs.py

lockfile-hashes:
	$(UV) run --no-project python scripts/hash_lockfiles.py --check

testdata:
	cd $(BACKEND) && $(UV) run python scripts/make_testdata.py --check

build: build-backend build-frontend

build-backend:
	cd $(BACKEND) && $(UV) build
	cd $(BACKEND) && $(UV) run python -c "import trendsmapp; print(trendsmapp.__version__)"

build-frontend:
	cd $(FRONTEND) && $(PNPM) run build

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs --tail=100 -f

clean:
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache $(BACKEND)/dist
	rm -rf $(FRONTEND)/.next $(FRONTEND)/coverage $(FRONTEND)/playwright-report
