# 0001. Stack choice and pinned versions

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

The project needs a pipeline that a reviewer can trust and reproduce:
extraction from the public GA4 sample in BigQuery, a cloud warehouse,
tested transformations, orchestration and dashboards. The budget is $0, so
every component must run on a free tier, a trial or a local machine. After
the Snowflake trial ends, the project must still run end to end without it.

## Decision

| Layer | Choice | Version | Why |
|---|---|---|---|
| Language | Python | 3.12 | Supported by every tool below and matches the Astro Runtime image, so the Mac, CI and Airflow run the same minor version. |
| Packaging | uv | 0.13.7 | Fast, reproducible installs from a committed lock file, with dependency groups per component. |
| Source | BigQuery public dataset | google-cloud-bigquery 3.47.0 | Sandbox access is free. Dry runs report bytes before a query runs. |
| File format | Parquet | pyarrow 26.0.1 | Keeps nested GA4 fields nested, and both Snowflake and DuckDB read it natively. |
| Warehouse | Snowflake (trial) | snowflake-connector-python 5.2.0 | Production-style warehouse with key-pair auth, roles and resource monitors. |
| Transformation | dbt Core | 1.12.6 | Tests, contracts, unit tests, documentation and lineage in one tool. |
| Adapters | dbt-snowflake, dbt-duckdb | 1.12.5, 1.11.1 | One project, two targets. DuckDB keeps the project reproducible for free and lets CI run without credentials. |
| Local engine | DuckDB | 1.5.6 | Mature 1.5 line. Reads Parquet directly. |
| Shared macros | dbt_utils | 1.4.1 | Surrogate keys, expression tests, date spine. |
| Orchestration | Airflow 3 on Astro Runtime 3.3, with Astronomer Cosmos | Runtime 3.3-9 (Airflow 3.3.2), Cosmos 1.16.0 | Industry-standard scheduler. Cosmos renders each dbt model as its own task. Exact image tag and Cosmos version are confirmed again in M5. |
| Containers | Docker Desktop | Current release | Assumed by the Astro CLI documentation. Free for personal and educational use. |
| BI | Metabase (self-hosted) and Power BI (school account) | Pinned in M6 and M7 | One open-source tool and one tool widely used by employers. |
| Quality | ruff, sqlfluff, pytest, pre-commit, gitleaks | 0.17.4, 4.5.0, 9.2.0, 4.7.0, 8.30.1 | Linting, formatting, tests and secret scanning, locally and in CI. |

Compatibility was checked by resolving the full dependency set together with
uv on Python 3.12, then running a dbt build on DuckDB with dbt-core 1.12.6,
dbt-snowflake 1.12.5 and dbt-duckdb 1.11.1 installed side by side.

Two smaller decisions follow from network and reproducibility constraints:

- **dbt_utils comes from a git tag, not the dbt package hub.** A pinned git
  tag installs identically everywhere, including networks that block the hub.
  `package-lock.yml` records the exact commit.
- **gitleaks in CI runs the release binary with a verified checksum**, not a
  third-party action, so the workflow needs no token or licence key.

## Alternatives considered

- **dbt v2.** It is now the default for new dbt installations. It was not
  chosen because its built-in DuckDB driver is reported not to load the
  Parquet extension that the free DuckDB path depends on, Cosmos 1.16 support
  for dbt 2 is still early, and dbt-duckdb targets dbt Core 1.x.
- **DuckDB 2.0.0.** Released on 21 October 2026. A small test passed, but a
  major release only weeks old is a risk for CI. It can be adopted later in
  its own pull request.
- **Airflow 2.** Still common in job postings, but Airflow 3 is the current
  line on Astro Runtime and is supported by Cosmos.
- **Dagster or Prefect.** Both are good fits for dbt, but Airflow remains the
  most requested orchestrator in analytics engineering roles.
- **Skipping Snowflake and using BigQuery throughout.** Simpler, but it would
  not show loading, warehouse security or cost controls in a second platform.
- **OrbStack or Colima instead of Docker Desktop.** Both are free and lighter
  on Apple silicon, but the Astro CLI documentation assumes Docker Desktop,
  which makes troubleshooting simpler.

## Consequences

- Every dbt model must compile on both Snowflake and DuckDB. Syntax that
  differs between the two lives only in `adapter.dispatch` macros.
- SQL is linted with the Snowflake dialect and the jinja templater, so linting
  needs no warehouse connection or credentials.
- All versions are pinned exactly in `pyproject.toml` and `uv.lock`. Upgrades
  happen in small, separate pull requests.

## Revisit when

- dbt v2 supports reading Parquet from DuckDB and Cosmos documents full dbt 2
  support.
- DuckDB 2.x has had several patch releases and dbt-duckdb lists it as tested.
- The Snowflake trial ends, at which point DuckDB becomes the primary target.
