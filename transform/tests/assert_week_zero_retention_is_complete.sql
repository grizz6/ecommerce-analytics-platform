{#
    Every user in a cohort is active in the cohort's first week by
    definition, so week 0 retention must be exactly 1. Returns rows that
    break this.
#}

select
    cohort_week_start_date,
    first_touch_channel_group,
    first_device_category,
    cohort_users,
    active_users,
    retention_rate
from {{ ref('fct_retention_weekly') }}
where
    weeks_since_first_visit = 0
    and (active_users != cohort_users or retention_rate != 1)
