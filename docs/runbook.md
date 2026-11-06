# Runbook

Operational steps for running the pipeline. Commands run from the repository
root on the machine that holds the credentials. Sections for loading,
orchestration and teardown are added in later milestones.

## Extract from BigQuery

### Prerequisites

- Google Cloud CLI installed and signed in with Application Default
  Credentials (`gcloud auth application-default login`). No key files.
- A Google Cloud project in BigQuery sandbox mode, with no billing account.
- A `.env` file copied from `.env.example`, with `GCP_PROJECT_ID` set to that
  project. `.env` is gitignored and must never be committed.

### Cost guardrails

| Setting | Default | Purpose |
|---|---|---|
| `BQ_MAX_BYTES_PER_QUERY` | 2 GiB | No single day may process more. Also sent to BigQuery as `maximum_bytes_billed`, so BigQuery rejects a larger query itself. |
| `BQ_MAX_BYTES_PER_RUN` | 100 GiB | The planned total for one run may not exceed this. |

Every run dry-runs all requested days first. Dry runs are free. If any day or
the total is over its limit, the run stops before any real query.

### Commands

Estimate bytes without running any query (free):

```bash
make extract-plan DATE=2020-11-01
```

```bash
make extract-plan
```

Extract one day, a range, or the full dataset (2020-11-01 to 2021-01-31):

```bash
make extract DATE=2020-11-01
```

```bash
make extract START=2020-11-01 END=2020-11-30
```

```bash
make extract
```

Print totals from the manifest (counts and bytes only, safe to share):

```bash
make extract-summary
```

### Output

- One file per day: `data/raw/ga4/event_date=YYYYMMDD/part-0.parquet`.
- A manifest, `data/raw/ga4/_manifest.json`, with rows, estimated bytes,
  processed bytes, billed bytes, file checksum and extraction time per day.
- Both live under `data/`, which is gitignored.

### Rerunning a day

Rerunning a day replaces its file and its manifest entry. The file is written
under a temporary name and renamed when complete, so an interrupted run never
leaves a partial file behind.

### Troubleshooting

| Message | Fix |
|---|---|
| `GCP_PROJECT_ID must be set` | Add the project ID to `.env`. |
| `Google credentials were not found` | Run `gcloud auth application-default login`. |
| `... above the per-query limit` | Check the estimate with `make extract-plan`. Raise `BQ_MAX_BYTES_PER_QUERY` in `.env` only if the estimate is expected. |
| `returned no rows` | The daily table does not exist for that date. |
