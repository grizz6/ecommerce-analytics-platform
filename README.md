# E-commerce Analytics Platform

[![CI](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/ci.yml)
[![dbt docs](https://github.com/grizz6/ecommerce-analytics-platform/actions/workflows/docs.yml/badge.svg)](https://grizz6.github.io/ecommerce-analytics-platform/)

An analytics engineering pipeline for the Google Analytics 4 sample e-commerce
dataset. Data is extracted from BigQuery, loaded into Snowflake, modelled with
dbt, orchestrated with Airflow and presented in Metabase and Power BI.

**Status:** in development. The full README, with architecture, setup steps
and findings, is written in the final milestone.

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
- [Decision records](docs/decisions/): why each part of the stack works the way it does.

## License

[MIT](LICENSE)
