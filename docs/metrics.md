# Metric definitions

Every metric below is defined exactly as the dbt model computes it. Model and
column names are given so each number can be traced to its SQL.

## Conventions

- **Reporting time zone.** Dates are in `America/New_York` (US East Coast).
  Event timestamps are stored in UTC.
- **Complete days.** The GA4 daily tables are UTC days, so the first and last
  East Coast dates are partial. Daily and weekly metrics cover the 91
  complete days, 2020-11-01 to 2021-01-30 (`dim_date.is_complete_reporting_day`).
- **Complete weeks.** Retention uses ISO weeks (Monday to Sunday) whose seven
  days are all complete (`dim_date.is_complete_week`): the weeks starting
  2020-11-02 to 2021-01-18.
- **Sessions.** A session is one `user_pseudo_id` and `ga_session_id` pair.
  Its date is the reporting date of its first event.
- **Orders.** One order per valid transaction id (not null, not empty, not
  `(not set)`); a repeated transaction id counts once. A purchase without a
  valid transaction id is its own order. Revenue is the order's
  `purchase_revenue_in_usd`, including tax and shipping, or 0 when not logged.
- **Division.** Every rate divides as double precision and is null when the
  denominator is 0.

## Headline KPIs (`kpi_daily`)

| Metric | Column | Definition |
|---|---|---|
| Sessions | `sessions` | Count of sessions whose session date is the day. |
| Users | `users` | Distinct users with at least one session on the day. |
| New users | `new_users` | Distinct users with a session on the day that is their first ever (`ga_session_number = 1`). |
| Purchasing sessions | `purchasing_sessions` | Sessions on the day with at least one `purchase` event. |
| Purchases | `purchases` | Orders whose order date is the day. |
| Revenue | `revenue_usd` | Sum of order revenue for orders placed on the day. |
| Conversion rate | `conversion_rate` | Purchasing sessions / sessions. |
| Average order value | `average_order_value_usd` | Revenue / purchases. |
| Revenue per user | `revenue_per_user_usd` | Revenue / users. |

Users and new users are distinct counts per day and are not additive across
days. Sessions, purchases and revenue are additive. Over a period, recompute
the rates from the summed counts rather than averaging daily rates.

## Funnel (`fct_funnel_daily`)

Grain: session date, device category and channel group, on complete days.

The funnel is **closed**: a session counts at a step only if it logged that
step and every earlier one, in this order: `view_item`, `add_to_cart`,
`begin_checkout`, `add_shipping_info`, `add_payment_info`, `purchase`.
Steps are matched by whether the event occurs in the session, not by
timestamp order.

| Metric | Column | Definition |
|---|---|---|
| Step sessions | `<step>_sessions` | Sessions that reached the step through every earlier step. |
| Any purchase | `purchase_sessions_any` | Sessions with any `purchase` event, whether or not earlier steps were logged. |
| View item rate | `view_item_rate` | `view_item_sessions` / `sessions`. |
| Step conversion | `<step>_rate` | Step sessions / sessions at the previous step. |
| Overall conversion | `overall_conversion_rate` | `purchase_sessions_any` / `sessions`. Same definition as the KPI conversion rate. |

GA4 does not guarantee that earlier steps are logged, so some purchasing
sessions skip steps. They are counted in `purchase_sessions_any` and in
overall conversion, but not in the closed step counts. The warning test
`warn_funnel_steps_logged_out_of_order` reports how many sessions this
affects on every run.

## Attribution (`fct_channel_attribution`)

Grain: order date, channel group and attribution model, on complete days.

**Touchpoints** for an order are the ordering user's sessions that started
within 30 days before the order, up to and including the order time
(`var('attribution_lookback_days')`). The order's own session is always one.

| Model | `attribution_model` | Credit |
|---|---|---|
| First touch | `first_touch` | The earliest touchpoint gets the whole order. |
| Last non-direct touch | `last_non_direct` | The latest touchpoint whose channel is not Direct gets the whole order. If every touchpoint is Direct, the latest one does. |
| Linear | `linear` | Each touchpoint gets 1 / number of touchpoints. |

| Metric | Column | Definition |
|---|---|---|
| Attributed orders | `attributed_orders` | Sum of credit given to the channel. Fractional under linear. |
| Attributed revenue | `attributed_revenue_usd` | Sum of credit multiplied by order revenue. |

Under every model, attributed revenue summed over channels equals order
revenue; the test `assert_attribution_credit_matches_order_revenue` checks
this for every order. Orders in early November have a shorter effective
lookback because sessions before 2020-11-01 are not in the data.

## Retention (`fct_retention_weekly`)

Grain: cohort week, activity week, first-touch channel and first device.

| Metric | Column | Definition |
|---|---|---|
| Cohort | `cohort_week_start_date` | Monday of the week of a user's first ever session (`ga_session_number = 1`). Users first seen on a later session were acquired before the data starts and are excluded. |
| Weeks since first visit | `weeks_since_first_visit` | Whole weeks from the cohort week to the activity week; 0 is the cohort week itself. |
| Cohort users | `cohort_users` | New users in the cohort, channel and device. |
| Active users | `active_users` | Cohort users with at least one session in the activity week. |
| Retention rate | `retention_rate` | Active users / cohort users. |

Week 0 retention is 1 by definition, checked by
`assert_week_zero_retention_is_complete`. Cohort users and active users are
additive across channels and devices within a cohort and week, so totals are
recomputed as summed active users / summed cohort users.

## Sessions, orders and users

| Metric | Model and column | Definition |
|---|---|---|
| Engaged session | `fct_sessions.is_engaged` | Any event in the session marked `session_engaged = 1` by GA4. |
| Session duration | `fct_sessions.session_duration_seconds` | Seconds from the first to the last event. |
| Landing page | `fct_sessions.landing_page` | `page_location` of the first `page_view`. |
| Channel group | `session_channel_group` | GA4 default channel group of the session's source, medium and campaign (decision record 0004). |
| First-touch channel | `dim_users.first_touch_channel_group` | Channel group of the user's first observed session. |
| Purchaser | `dim_users.is_purchaser` | The user placed at least one order. |
