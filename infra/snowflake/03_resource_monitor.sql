-- 03. Account-wide credit cap.
--
-- 50 credits for the whole trial (about $100 of the $400 trial credit on
-- Standard edition). FREQUENCY = NEVER means the quota never resets, so it is
-- a total, not a monthly allowance. Applied at account level, it covers every
-- warehouse, including COMPUTE_WH.
--
-- Notifications go to account administrators who have a verified email and
-- have enabled resource monitor notifications in their Snowsight settings.
-- Resource monitors cover warehouse compute only. Storage and serverless
-- features are not counted; see the credit usage checks in docs/runbook.md.

use role accountadmin;

create resource monitor if not exists project_credit_cap
    with
    credit_quota = 50
    frequency = never
    start_timestamp = immediately
    triggers
        on 50 percent do notify
        on 75 percent do notify
        on 90 percent do suspend
        on 100 percent do suspend_immediate;

alter account set resource_monitor = project_credit_cap;
