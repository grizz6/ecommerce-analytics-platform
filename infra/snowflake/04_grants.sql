-- 04. Least-privilege grants. Run after 00 to 03. Safe to rerun.
--
-- LOADER       writes raw.ga4.events and its stage. Nothing else.
-- TRANSFORMER  reads RAW and builds schemas and models in ANALYTICS.
-- REPORTER     reads tables and views in analytics.marts. Nothing else.

use role securityadmin;

-- LOADER
grant usage on warehouse loading_wh to role loader;
grant usage on database raw to role loader;
grant usage on schema raw.ga4 to role loader;
grant select, insert, delete on table raw.ga4.events to role loader;
grant read, write on stage raw.ga4.events_stage to role loader;
grant usage on file format raw.ga4.parquet_format to role loader;

-- TRANSFORMER
grant usage on warehouse transforming_wh to role transformer;
grant usage on database raw to role transformer;
grant usage on schema raw.ga4 to role transformer;
grant select on all tables in schema raw.ga4 to role transformer;
grant select on future tables in schema raw.ga4 to role transformer;
grant usage, create schema on database analytics to role transformer;

-- REPORTER: future grants apply to every table and view dbt creates or
-- replaces in the marts schema, so no grant step is needed after each build.
grant usage on warehouse reporting_wh to role reporter;
grant usage on database analytics to role reporter;
grant usage on schema analytics.marts to role reporter;
grant select on all tables in schema analytics.marts to role reporter;
grant select on all views in schema analytics.marts to role reporter;
grant select on future tables in schema analytics.marts to role reporter;
grant select on future views in schema analytics.marts to role reporter;
