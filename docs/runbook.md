# Runbook

Operational steps for running the pipeline. Commands run from the repository
root on the machine that holds the credentials. Sections for loading,
orchestration and teardown are added in later milestones.

## Extract from BigQuery

### Prerequisites

- Google Cloud CLI installed and signed in with Application Default
  Credentials (`gcloud auth application-default login`). No key files.
- A Google Cloud project in BigQuery sandbox mode, with no billing account.
- `GCP_PROJECT_ID` set in the current Terminal window, read from the gcloud
  configuration so it is never typed or saved in the project:

```bash
export GCP_PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
```

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
| `GCP_PROJECT_ID must be set` | Run the `export GCP_PROJECT_ID=...` command above in this Terminal window. |
| `Google credentials were not found` | Run `gcloud auth application-default login`. |
| `... above the per-query limit` | Check the estimate with `make extract-plan`. Raise `BQ_MAX_BYTES_PER_QUERY` (for example `export BQ_MAX_BYTES_PER_QUERY=3000000000`) only if the estimate is expected. |
| `returned no rows` | The daily table does not exist for that date. |

## Snowflake setup (one time)

### 1. Create key pairs

Each service user has its own key pair. The private key is encrypted
(PKCS#8, AES-256) and never leaves `~/.snowflake/keys/`. Each command asks
for a passphrase; use a different one per key and keep them in a password
manager.

```bash
mkdir -p ~/.snowflake/keys && chmod 700 ~/.snowflake/keys
```

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM -out ~/.snowflake/keys/loader_svc.p8
```

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM -out ~/.snowflake/keys/dbt_svc.p8
```

```bash
chmod 600 ~/.snowflake/keys/*.p8
```

Print a public key as one line, ready to paste into Snowsight (asks for that
key's passphrase):

```bash
openssl rsa -in ~/.snowflake/keys/loader_svc.p8 -pubout | grep -v "PUBLIC KEY" | tr -d '\n'; echo
```

### 2. Run the setup scripts

In Snowsight, as a user with ACCOUNTADMIN, run each file in
`infra/snowflake/` in order: `00`, `01`, `02`, `03`, `04`. For `02_users.sql`,
paste the file into a worksheet and replace the placeholders there with the
public keys. Never save real keys into the repository file.

Then enable resource monitor emails: user menu, **Settings**,
**Notifications**, and turn on email notifications for resource monitors.

### 3. Rotate a key

Snowflake allows two public keys per user. Add the new one, switch the
private key file, then remove the old one:

```sql
alter user loader_svc set rsa_public_key_2 = '<NEW_PUBLIC_KEY>';
alter user loader_svc unset rsa_public_key;
```

## Load into Snowflake

### Settings

The loader reads these from the environment. Only the first two have no
default.

| Variable | Default |
|---|---|
| `SNOWFLAKE_ACCOUNT` | none (account identifier, `ORGNAME-ACCOUNTNAME`) |
| `SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE` | none |
| `SNOWFLAKE_LOADER_PRIVATE_KEY_PATH` | `~/.snowflake/keys/loader_svc.p8` |
| `SNOWFLAKE_LOADER_USER` | `LOADER_SVC` |
| `SNOWFLAKE_LOADER_ROLE` | `LOADER` |
| `SNOWFLAKE_LOADER_WAREHOUSE` | `LOADING_WH` |
| `SNOWFLAKE_RAW_DATABASE` | `RAW` |

To keep both values out of files and shell history, type them at a hidden
prompt for the current Terminal window only. These commands work in both bash
and zsh. Paste or type the value and press Enter; nothing is shown while you
type. Use the account identifier with a hyphen (`ORGNAME-ACCOUNTNAME`).

```bash
printf "Account identifier: "; read -rs SNOWFLAKE_ACCOUNT; export SNOWFLAKE_ACCOUNT; echo
```

```bash
printf "Loader key passphrase: "; read -rs SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE; export SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE; echo
```

### Commands

```bash
make load DATE=2020-11-01
```

```bash
make load
```

```bash
make reconcile
```

`make load` replaces each requested day in one transaction and checks the
rows loaded against the manifest before committing. `make reconcile` exits
with status 1 if any day is missing, extra or has a different count.

### Rerunning a day

Run `make load DATE=YYYY-MM-DD` again. The day's stage file is replaced, its
rows are deleted and reloaded, and the transaction commits only if the count
matches. Other days are untouched.

### Troubleshooting

| Message | Fix |
|---|---|
| `SNOWFLAKE_ACCOUNT must be set` | Run the `printf ...; read ...` commands above in this Terminal window. |
| `private key file is readable by other users` | `chmod 600 ~/.snowflake/keys/*.p8` |
| `Could not read the private key` | The passphrase is wrong for that key. |
| `Authentication failed. Unspecified` | The passphrase does not unlock the key file. Check it with the passphrase check below, or create a new key. |
| `JWT token is invalid` | The public key on the user does not match this private key. Set it again (see "Rotate a key"). |
| `does not exist or not authorized` | The service user is missing or misspelled. Rerun `02_users.sql`. |
| `HTTP request failed` | Snowflake could not be reached. See "Diagnose a connection failure" below. |
| `Insufficient privileges` | Rerun `04_grants.sql`. |
| `does not match its manifest checksum` | Re-extract that day, then load it. |

### Diagnose a connection failure

Each check prints only a result, never the account identifier or passphrase,
so the output is safe to share.

The passphrase in this Terminal window must unlock the key file:

```bash
openssl pkey -in ~/.snowflake/keys/loader_svc.p8 -noout -passin env:SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE 2>/dev/null && echo "passphrase correct" || echo "passphrase wrong"
```

The identifier must be `ORGNAME-ACCOUNTNAME`: letters, digits and underscores
on each side of one hyphen. No dots, no `https://`, no `.snowflakecomputing.com`.

```bash
[[ "$SNOWFLAKE_ACCOUNT" =~ ^[A-Za-z0-9_]+-[A-Za-z0-9_]+$ ]] && echo "format ok" || echo "format wrong"
```

The account's address must resolve:

```bash
host "$SNOWFLAKE_ACCOUNT.snowflakecomputing.com" >/dev/null 2>&1 && echo "address resolves" || echo "address does not resolve"
```

Proxy variables in the shell redirect the connection. List their names only:

```bash
env | grep -i '_proxy=' | cut -d= -f1
```

If any are listed and you do not need a proxy, clear them for this window:

```bash
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
```

## Run dbt on Snowflake

One-time setup: copy the profile template.

```bash
mkdir -p ~/.dbt && cp transform/profiles.example.yml ~/.dbt/profiles.yml
```

In each new Terminal window, set the two values that have no default:

```bash
read -rsp "Account identifier: " SNOWFLAKE_ACCOUNT && export SNOWFLAKE_ACCOUNT && echo
```

```bash
read -rsp "dbt key passphrase: " SNOWFLAKE_DBT_PRIVATE_KEY_PASSPHRASE && export SNOWFLAKE_DBT_PRIVATE_KEY_PASSPHRASE && echo
```

Build and test everything in the development schemas (`DEV_STAGING`,
`DEV_INTERMEDIATE` and so on):

```bash
make dbt-snowflake
```

Use `TARGET=prod` to build the production schemas (`STAGING`, `MARTS` and so
on). After changing how `event_key` is built, run once with a full refresh:

```bash
cd transform && uv run dbt build --target dev --full-refresh
```

## Orchestration with Airflow

The `ga4_daily` DAG runs one GA4 day per run: extract, load, reconcile, then
build and test every dbt model (Cosmos, one task per model), then a summary.
It covers 2020-11-01 to 2021-01-31 with catchup on and one run at a time.

### One-time setup

1. Docker Desktop, **Settings → Resources**: Memory **8 GB**, CPUs **4**,
   Swap **1 GB**. Enough for Airflow now and Metabase later on an 18 GB Mac.
2. Install the Astro CLI and check it:

```bash
brew install astro
```

```bash
astro version
```

3. Install the dbt packages Airflow copies with the project:

```bash
make setup
```

4. Write Airflow's settings. Asks for the Snowflake account identifier and
   both key passphrases at hidden prompts, and writes `orchestration/.env`
   with owner-only permissions. The file is gitignored.

```bash
make airflow-env
```

### Start

```bash
make airflow-start
```

The first start builds the image (a few minutes). Open the Airflow UI at the
address the command prints. Keys and Google credentials are mounted
read-only from this Mac; nothing secret is built into the image.

### Backfill

The DAG is created paused. Turning it on in the UI starts the backfill: one
run per day from 2020-11-01, oldest first, one at a time. To backfill only a
range, for example the first week:

```bash
cd orchestration && astro dev run backfill create --dag-id ga4_daily --from-date 2020-11-01 --to-date 2020-11-07
```

Every step is idempotent, so backfilling days that already exist replaces
them without duplicates.

### Rerun a failed day

In the UI, open **ga4_daily → Grid**, select the failed run and **Clear**
the failed task; it reruns with its downstream tasks. From the command line:

```bash
cd orchestration && astro dev run tasks clear ga4_daily --start-date 2020-11-05 --end-date 2020-11-05 --yes
```

### Stop and tear down

Stop the containers and keep run history:

```bash
make airflow-stop
```

Remove the containers and Airflow's metadata database (run history is lost;
Snowflake and the Parquet files are not touched):

```bash
cd orchestration && astro dev kill
```

### Tests

```bash
make airflow-test
```

`make dag-test` runs the same tests without Docker, as CI does.

### Cost

Extract stays within the BigQuery sandbox (about 35 MB per day). Each run
keeps an extra-small warehouse busy for a few minutes, so a full 92-day
backfill is expected to use a few credits. Check with the credit usage
queries below after backfilling the first week.

### Screenshots

The grid view and the dbt task graph show no account details. Do not capture
**Admin → Connections**, which shows the account identifier.

## Credit usage checks

Run in Snowsight as ACCOUNTADMIN. The resource monitor view is close to real
time; `ACCOUNT_USAGE` views can lag by up to three hours.

Credits used against the project cap:

```sql
show resource monitors like 'PROJECT_CREDIT_CAP';
```

Credits per warehouse per day, last 30 days:

```sql
select
    to_date(start_time) as usage_date,
    warehouse_name,
    round(sum(credits_used), 4) as credits_used
from snowflake.account_usage.warehouse_metering_history
where start_time >= dateadd(day, -30, current_timestamp())
group by usage_date, warehouse_name
order by usage_date, warehouse_name;
```

Total credits by service type, including cloud services, last 30 days:

```sql
select
    service_type,
    round(sum(credits_used), 4) as credits_used
from snowflake.account_usage.metering_daily_history
where usage_date >= dateadd(day, -30, current_date())
group by service_type
order by credits_used desc;
```

Warehouses that are not suspended right now (should usually be empty):

```sql
show warehouses;
```
