SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
DBT_DIR := transform
DUCKDB_DIR := $(CURDIR)/data/duckdb
FIXTURE_DIR := $(CURDIR)/data/fixtures/ga4
DBT_CI_ENV := DBT_PROFILES_DIR=$(CURDIR)/$(DBT_DIR)/ci DBT_DUCKDB_PATH=$(DUCKDB_DIR)/ci.duckdb
DBT_CI := cd $(DBT_DIR) && $(DBT_CI_ENV) $(UV) run dbt

# Extraction: DATE=YYYY-MM-DD for one day, or START=... END=... for a range.
# With neither, the full configured range is used. Settings come from
# environment variables; see docs/runbook.md.
EXTRACT_ARGS := $(if $(DATE),--date $(DATE),$(if $(START),--start $(START) --end $(or $(END),$(START)),))
EXTRACT := $(UV) run python -m extract_load.bigquery_extract
LOAD := $(UV) run python -m extract_load.snowflake_load
RECONCILE := $(UV) run python -m extract_load.reconcile

.PHONY: help setup lint format test fixtures dbt-deps dbt-ci docs docs-check secrets clean \
	extract-plan extract extract-summary load reconcile dbt-snowflake

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install pinned dependencies, git hooks and dbt packages
	$(UV) sync --all-groups --locked
	$(UV) run pre-commit install
	$(DBT_CI) deps

lint: dbt-deps ## Run ruff and sqlfluff without changing files
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run sqlfluff lint infra
	$(UV) run sqlfluff lint transform --templater dbt

format: ## Apply ruff formatting and safe fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test: ## Run the Python test suite with coverage
	$(UV) run pytest

fixtures: ## Generate synthetic GA4 fixture data (fixed seed)
	$(UV) run python -m scripts.generate_fixtures --output-dir $(FIXTURE_DIR)

dbt-deps: ## Install dbt packages
	$(DBT_CI) deps

dbt-ci: fixtures dbt-deps ## Build and test every dbt model on DuckDB fixtures
	mkdir -p $(DUCKDB_DIR)
	$(DBT_CI) build --target ci

docs: dbt-deps ## Generate static dbt docs from the DuckDB target
	mkdir -p $(DUCKDB_DIR)
	$(DBT_CI) docs generate --static --target ci

docs-check: ## Fail if any dbt model, seed or column lacks a description
	$(DBT_CI) parse --target ci
	$(UV) run python -m scripts.check_dbt_docs

extract-plan: ## Dry-run BigQuery for DATE or START/END and report bytes (free)
	$(EXTRACT) $(EXTRACT_ARGS) --dry-run

extract: ## Extract DATE or START/END from BigQuery to data/raw/ga4
	$(EXTRACT) $(EXTRACT_ARGS)

extract-summary: ## Print row and byte totals from the extract manifest
	$(EXTRACT) --summary

load: ## Load extracted DATE or START/END into Snowflake RAW.GA4.EVENTS
	$(LOAD) $(EXTRACT_ARGS)

reconcile: ## Compare per-day row counts between the manifest and Snowflake
	$(RECONCILE)

dbt-snowflake: ## Build and test dbt on Snowflake (TARGET=dev or prod; profile in ~/.dbt)
	cd $(DBT_DIR) && $(UV) run dbt deps && $(UV) run dbt build --target $(or $(TARGET),dev)

secrets: ## Scan git history and staged changes for secrets (needs gitleaks installed)
	gitleaks git --redact --no-banner .
	gitleaks git --redact --no-banner --staged .

clean: ## Remove generated data and build output
	rm -rf $(CURDIR)/data/fixtures $(DUCKDB_DIR) $(DBT_DIR)/target $(DBT_DIR)/dbt_packages $(DBT_DIR)/logs
