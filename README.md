# E-commerce Analytics Platform

An analytics engineering pipeline for the Google Analytics 4 sample e-commerce
dataset. Data is extracted from BigQuery, loaded into Snowflake, modelled with
dbt, orchestrated with Airflow and presented in Metabase and Power BI.

**Status:** in development. The full README, with architecture, setup steps
and findings, will be written in the final milestone.

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
make setup     # install pinned dependencies, git hooks and dbt packages
make lint      # ruff and sqlfluff
make test      # pytest with coverage
make dbt-ci    # generate fixtures, then build and test dbt models on DuckDB
make docs      # static dbt documentation
```

## Decisions

Architecture decision records live in [docs/decisions](docs/decisions/).

## License

[MIT](LICENSE)
