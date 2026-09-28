# Keep AIRFLOW_VERSION in sync with the image tag in the Dockerfile.
AIRFLOW_VERSION := 3.3.2
PYTHON_VERSION := 3.14
CONSTRAINTS := https://raw.githubusercontent.com/apache/airflow/constraints-$(AIRFLOW_VERSION)/constraints-$(PYTHON_VERSION).txt

PY := .venv/bin/python
DBT := $(CURDIR)/.venv-dbt/bin/dbt
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.PHONY: help setup up down logs test test-unit extract load dbt-build dbt-docs trigger clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create .venv (app + tests + Airflow) and .venv-dbt (dbt)
	uv venv --allow-existing --python $(PYTHON_VERSION) .venv
	uv pip install --python .venv -r requirements-dev.txt "apache-airflow==$(AIRFLOW_VERSION)" --constraint $(CONSTRAINTS)
	uv venv --allow-existing --python $(PYTHON_VERSION) .venv-dbt
	uv pip install --python .venv-dbt -r requirements-dbt.txt

up:  ## Build and start Postgres + Airflow (UI at http://localhost:8080)
	docker compose up -d --build

down:  ## Stop the stack (data is kept in Docker volumes)
	docker compose down

logs:  ## Follow Airflow logs
	docker compose logs -f airflow

test:  ## Run all tests (database tests need `make up`)
	$(PY) -m pytest

test-unit:  ## Run only the tests that don't need a database
	$(PY) -m pytest -m "not integration"

extract:  ## Fetch one snapshot from OpenSky into data/raw
	$(PY) -m extract.run

load:  ## Load new raw files into the warehouse
	$(PY) -m load.run

dbt-build:  ## Build dbt models and run dbt tests against the local warehouse
	$(DBT) build $(DBT_ARGS)

dbt-docs:  ## Generate and serve dbt docs at http://localhost:8081
	$(DBT) docs generate $(DBT_ARGS) && $(DBT) docs serve $(DBT_ARGS) --port 8081

trigger:  ## Trigger the Airflow DAG now instead of waiting for the schedule
	docker compose exec airflow airflow dags trigger flight_tracking

clean:  ## Remove dbt build output and Python caches
	rm -rf dbt/target dbt/logs .pytest_cache
	find . -name __pycache__ -not -path './.venv*' -exec rm -rf {} +
