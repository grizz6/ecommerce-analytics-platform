-- 00. Roles and warehouses.
-- Run in Snowsight while signed in as a user with ACCOUNTADMIN. Each section
-- switches to the narrowest built-in role that can do the work. Safe to rerun.

-- Functional roles: one per job, each with only the access it needs.
use role useradmin;

create role if not exists loader
    comment = 'Writes raw GA4 data into the RAW database only.';

create role if not exists transformer
    comment = 'Reads RAW and builds dbt models in the ANALYTICS database.';

create role if not exists reporter
    comment = 'Reads the published marts only. Used by BI tools.';

-- Custom roles roll up to SYSADMIN so administrators can manage their objects.
use role securityadmin;

grant role loader to role sysadmin;
grant role transformer to role sysadmin;
grant role reporter to role sysadmin;

-- One extra-small warehouse per workload, so credit usage is visible per job.
-- Each suspends after 60 seconds idle and starts only when a query arrives.
use role sysadmin;

create warehouse if not exists loading_wh
    warehouse_size = 'XSMALL'
    auto_suspend = 60
    auto_resume = true
    initially_suspended = true
    comment = 'Loads raw files. Used by LOADER.';

create warehouse if not exists transforming_wh
    warehouse_size = 'XSMALL'
    auto_suspend = 60
    auto_resume = true
    initially_suspended = true
    comment = 'Runs dbt. Used by TRANSFORMER.';

create warehouse if not exists reporting_wh
    warehouse_size = 'XSMALL'
    auto_suspend = 60
    auto_resume = true
    initially_suspended = true
    comment = 'Serves dashboards. Used by REPORTER.';

-- The trial creates COMPUTE_WH for Snowsight. Apply the same cost settings.
alter warehouse if exists compute_wh set
    warehouse_size = 'XSMALL'
    auto_suspend = 60
    auto_resume = true;
