.PHONY: help venv install up up-detached down clean logs status seed test test-cov lint typecheck check fmt smoke

PYTHON ?= python3.11
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python

help:  ## list available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' Makefile | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

# ── dev environment ──────────────────────────────────────────────────

venv:  ## create local Python venv (3.11+)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv  ## install project + dev deps into the venv
	$(PIP) install -e ".[dev]"

# ── docker-compose stack ─────────────────────────────────────────────

up:  ## build and run the full local stack (broker, control-plane, audit-service, metering-service, DynamoDB Local, MinIO, ClickHouse)
	docker compose up --build

up-detached:  ## like 'up' but in the background
	docker compose up --build -d

down:  ## stop the stack (keep volumes)
	docker compose down

clean:  ## stop the stack and wipe all volumes
	docker compose down -v --remove-orphans

logs:  ## tail logs from all services
	docker compose logs -f

status:  ## show stack status + healthz of each service
	@docker compose ps
	@echo
	@echo "── healthz ──"
	@for url in \
	    http://localhost:8080/healthz \
	    http://localhost:8090/healthz \
	    http://localhost:8086/healthz \
	    http://localhost:8087/healthz ; do \
	    printf "  %-40s " "$$url"; curl -s -m 2 "$$url" || echo "(unreachable)"; echo; \
	done

seed:  ## post a couple of sample provisioning requests so the dashboards have data
	@./scripts/provision-demo.sh

# ── verification ─────────────────────────────────────────────────────

test:  ## run the full pytest suite (in venv)
	$(VENV)/bin/pytest -q

test-cov:  ## run pytest with coverage, enforce 80% floor
	$(VENV)/bin/pytest -q --cov --cov-report=term --cov-report=html --cov-fail-under=80

lint:  ## ruff lint
	$(VENV)/bin/ruff check libs apps tests

typecheck:  ## mypy on the shared lib surface
	$(VENV)/bin/mypy libs/common/sovereign

check: lint typecheck test  ## lint + typecheck + tests — the local equivalent of CI

fmt:  ## ruff lint with autofix (no formatter run; ruff format would re-flow code)
	$(VENV)/bin/ruff check libs apps tests --fix

# ── end-to-end smoke ─────────────────────────────────────────────────

smoke: up-detached  ## bring the stack up, exercise the broker, then tear down
	@echo "waiting for broker /healthz..."
	@for i in $$(seq 1 30); do \
	    curl -fs http://localhost:8080/healthz > /dev/null && break || sleep 1; \
	done
	@$(MAKE) seed
	@echo
	@$(MAKE) status
	@echo "smoke complete; 'make down' to stop the stack"
