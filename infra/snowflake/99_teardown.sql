-- 99. Teardown. Removes everything this project created.
--
-- Run only when you are finished with Snowflake, for example at the end of
-- the trial. This permanently deletes the loaded data and all dbt models.
-- The local Parquet files and the DuckDB path are unaffected.

use role accountadmin;

alter account unset resource_monitor;
drop resource monitor if exists project_credit_cap;

use role useradmin;

drop user if exists loader_svc;
drop user if exists dbt_svc;
drop user if exists bi_svc;

use role sysadmin;

drop database if exists analytics;
drop database if exists raw;
drop warehouse if exists loading_wh;
drop warehouse if exists transforming_wh;
drop warehouse if exists reporting_wh;

use role useradmin;

drop role if exists reporter;
drop role if exists transformer;
drop role if exists loader;
