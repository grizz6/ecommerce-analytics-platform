# GA4 sample: data notes

What this project found in `bigquery-public-data.ga4_obfuscated_sample_ecommerce`
and how the models handle it. Counts come from the profiling query below, run
on Snowflake after the first full dbt build (dev target).

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
- Exact duplicate rows in the real data: **none**. RAW and
  `stg_ga4__events` both hold 4,295,584 rows. Deduplication stays in place
  because a reload or a future export could introduce duplicates; the
  synthetic CI fixtures contain deliberate duplicates so the logic is still
  tested.

## Traffic fields available

| Field | Level | Notes |
|---|---|---|
| `traffic_source.source / medium / name` | User, first touch | Fixed per user, so it describes acquisition, not each session. |
| `event_params` `source`, `medium`, `campaign` | Event | Present on some events; the first one in a session sets the session's source. |
| `collected_traffic_source`, `session_traffic_source_last_click` | | Not in this export; added to GA4 exports in 2023. |

Sessions without any event-level traffic parameter are `(direct) / (none)`:
132,339 of 360,129 sessions (36.7%).

## Obfuscation

Values are kept as published and never corrected. Observed placeholders:

| Placeholder | Where | Effect |
|---|---|---|
| `(data deleted)` | Source, medium, campaign, region | Channel becomes Unassigned |
| `<Other>` | Source, medium, device and location fields | Channel becomes Unassigned |
| Empty string | Source, medium, city | Channel becomes Unassigned |
| INTEGER-typed blank fields | `user_properties`, `device.vendor_id`, `device.advertising_id` | Not used by any model |

Sessions in the Unassigned channel: 31,771 of 360,129 (8.8%). Channel results
should be read with this share in mind.

## Sessions without a session id

Events without `ga_session_id` cannot be placed in a session. They remain in
`stg_ga4__events` and are excluded from session models. In the real data
every event has a session id (0 events without one), so no event is lost. The
CI fixtures include such events to test the exclusion.

## Summary

| Measure | Value |
|---|---|
| Events (RAW and staged) | 4,295,584 |
| Exact duplicate events | 0 |
| Events without a session id | 0 |
| Sessions | 360,129 |
| Average events per session | 11.9 |
| Direct sessions | 132,339 (36.7%) |
| Unassigned sessions | 31,771 (8.8%) |

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
