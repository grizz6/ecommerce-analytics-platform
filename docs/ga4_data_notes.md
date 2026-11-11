# GA4 sample: data notes

What this project found in `bigquery-public-data.ga4_obfuscated_sample_ecommerce`
and how the models handle it. Numbers marked *pending* are filled in after the
profiling queries below are run on Snowflake.

## Time zones

- The daily tables are **UTC days**: for `event_date = 20201201`, the first and
  last event timestamps are 00:00:00 and 23:59:58 UTC.
- Reporting uses **US East Coast time** (`America/New_York`). As a result, the
  first East Coast date (2020-10-31) holds only about four hours of data and the
  last (2021-01-31) is missing its final five hours.
- Daily KPIs, trends and retention use the 91 complete days, 2020-11-01 to
  2021-01-30 (`first_complete_reporting_date`, `last_complete_reporting_date`).
  Detailed models keep every event.

## Duplicates

- The export has no event identifier. `event_key` fingerprints user,
  timestamp, event name, bundle sequence and all parameters.
- Exact duplicate rows: *pending* (rows in RAW minus rows in
  `stg_ga4__events`).

## Traffic fields available

| Field | Level | Notes |
|---|---|---|
| `traffic_source.source / medium / name` | User, first touch | Fixed per user, so it describes acquisition, not each session. |
| `event_params` `source`, `medium`, `campaign` | Event | Present on some events; the first one in a session sets the session's source. |
| `collected_traffic_source`, `session_traffic_source_last_click` | | Not in this export; added to GA4 exports in 2023. |

Sessions without any event-level traffic parameter are `(direct) / (none)`.
Share of sessions without traffic parameters: *pending*.

## Obfuscation

Values are kept as published and never corrected. Observed placeholders:

| Placeholder | Where | Effect |
|---|---|---|
| `(data deleted)` | Source, medium, campaign, region | Channel becomes Unassigned |
| `<Other>` | Source, medium, device and location fields | Channel becomes Unassigned |
| Empty string | Source, medium, city | Channel becomes Unassigned |
| INTEGER-typed blank fields | `user_properties`, `device.vendor_id`, `device.advertising_id` | Not used by any model |

Share of sessions in Unassigned: *pending*.

## Sessions without a session id

Events without `ga_session_id` cannot be placed in a session. They remain in
`stg_ga4__events` and are excluded from session models. Count: *pending*.

## Profiling queries

Run in Snowsight after `make dbt-snowflake`. They return counts only.

```sql
select
    (select count(*) from raw.ga4.events) as raw_rows,
    (select count(*) from analytics.dev_staging.stg_ga4__events) as staged_events,
    (select count(*) from analytics.dev_staging.stg_ga4__events where session_key is null)
        as events_without_session,
    (select count(*) from analytics.dev_intermediate.int_ga4__sessions) as sessions,
    (select count(*) from analytics.dev_intermediate.int_ga4__sessions
        where session_source = '(direct)' and session_medium = '(none)') as direct_sessions,
    (select count(*) from analytics.dev_intermediate.int_ga4__sessions
        where session_channel_group = 'Unassigned') as unassigned_sessions;
```
