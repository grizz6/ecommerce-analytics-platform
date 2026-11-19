# E-commerce Analytics Platform

[![CI](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/ci.yml)
[![dbt docs](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/docs.yml/badge.svg)](https://grizz6.github.io/ecommerce-analytics-platform/)

An analytics engineering pipeline for the Google Analytics 4 sample e-commerce
dataset. Data is extracted from BigQuery, loaded into Snowflake, modelled with
dbt, orchestrated with Airflow and presented in Metabase and Power BI.

**Status:** in development. The full README, with architecture, setup steps
and findings, is written in the final milestone.

## Progress to date

| Milestone | Scope | Status |
|---|---|---|
| M0 | Scaffold, tooling, CI | Done |
| M1 | Extract GA4 from BigQuery to Parquet | Done |
| M2 | Snowflake setup, load and reconciliation | Done |
| M3 | dbt staging and intermediate models | Done |
| M4 | Marts, tests, metric definitions, docs site | Done |
| M5 | Airflow orchestration | In review |
| M6 | Metabase dashboard | Planned |
| M7 | Power BI report | Planned |
| M8 | Findings and release | Planned |

### What is built

- **Extract (M1).** A Python extractor reads the 92 daily GA4 tables
  (2020-11-01 to 2021-01-31) from the public BigQuery dataset into daily
  Parquet files, keeping nested fields nested. Every query is dry-run first
  and refused above a byte limit. The full extract of 4,295,584 events
  processed 3.24 GiB, inside BigQuery's free tier.
- **Load (M2).** Snowflake is set up with least-privilege roles (load,
  transform, report), extra-small warehouses that suspend after 60 seconds,
  key-pair-only service users and a 50-credit spending cap. Each day loads
  in one transaction that replaces the day and commits only when row counts
  match; reconciliation matched all 92 days.
- **Model (M3, M4).** dbt builds staging, intermediate and eight mart tables
  answering the four business questions: funnel by device and channel,
  channel revenue under three attribution models, weekly retention cohorts,
  and daily KPIs. The same project runs on Snowflake and on DuckDB through
  cross-database macros. Marts enforce contracts and never expose raw user
  identifiers.
- **Test.** The full dbt build, with its data tests and unit tests, passes on
  Snowflake and on DuckDB, including checks that attribution credit adds up
  to order revenue and that week-0 retention is 100 percent. 152 Python tests
  cover extraction, loading and tooling with 98 percent coverage.
- **Orchestrate (M5, in review).** An Airflow 3 DAG runs extract, load,
  reconcile and a Cosmos dbt task group for each day, with retries and safe
  backfills. DAG integrity tests run in CI.
- **Automate.** Every push runs linting (Python and SQL), the Python tests,
  the dbt build on synthetic data, the DAG tests and a secret scan. The dbt
  documentation site is published on every change to `main`.

### What the checks found in the data

- No exact duplicate events, and every event belongs to a session.
- 16.9 percent of orders have no usable transaction id, and 6.1 percent of
  transactions were logged more than once; both are handled so revenue is
  neither lost nor double counted.
- 1.4 percent of sessions log a funnel step without the step before it, which
  GA4 does not prevent; a warning-level test reports it on every run.
- An early run found linear attribution three cents short in total, caused by
  six-decimal fixed-point division in Snowflake. It is fixed, and the tests
  now compare revenue to well under a cent.

Details are in the [GA4 data notes](docs/ga4_data_notes.md).

## Documentation site

**[grizz6.github.io/ecommerce-analytics-platform](https://grizz6.github.io/ecommerce-analytics-platform/)**

A browsable map of the dbt project, published automatically whenever `main`
changes. It lets anyone review how the pipeline is built without installing
anything or needing warehouse access:

- **Lineage:** a clickable graph from the raw GA4 source through staging and
  intermediate models to the marts and the dashboards that use them, so any
  number can be traced back to its source.
- **Documentation:** what every model and column means, and the SQL behind it.
  A CI check fails if any model or column is left undocumented.
- **Tests:** the checks that protect each table, such as unique keys,
  non-negative revenue, rates between 0 and 1, and attribution credit adding
  up to order revenue.

The site is built from synthetic fixture data, so it never contains real
event data or identifiers.

## Business questions

1. Where do shoppers drop out of the purchase funnel, and does it differ by
   device and channel?
2. Which acquisition channels drive revenue, and how does credit change under
   first-touch, last non-direct touch and linear attribution?
3. Do new users come back? Weekly retention by acquisition cohort, channel and
   device.
4. What are the headline KPIs and how did they trend?

## Local development

Requires [uv](https://docs.astral.sh/uv/) and GNU Make. Everything below runs
on synthetic data and needs no credentials.

```bash
make setup       # install pinned dependencies, git hooks and dbt packages
make lint        # ruff and sqlfluff (dbt models compiled by dbt first)
make test        # pytest with coverage
make dbt-ci      # generate fixtures, then build and test dbt models on DuckDB
make docs-check  # fail if any model or column has no description
make docs        # static dbt documentation
```

Running against BigQuery and Snowflake needs credentials on your own machine;
see the [runbook](docs/runbook.md).

## Reference

- [Metric definitions](docs/metrics.md): every metric exactly as the SQL computes it.
- [GA4 data notes](docs/ga4_data_notes.md): time zones, obfuscation, duplicates and data quality findings.
- [Runbook](docs/runbook.md): extract, load, dbt on Snowflake and credit checks.
- [Decision records](docs/decisions/README.md): why each part of the stack works the way it does.

## License

[MIT](LICENSE)
