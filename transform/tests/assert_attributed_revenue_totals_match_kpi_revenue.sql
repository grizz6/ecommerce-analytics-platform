{#
    For each attribution model, attributed revenue over all channels and
    complete days must equal the revenue in kpi_daily. Checks the totals the
    dashboards show, not only individual orders. Returns models that differ
    by more than a hundredth of a cent.
#}

with

kpi as (

    select sum(revenue_usd) as revenue_usd
    from {{ ref('kpi_daily') }}

),

attributed as (

    select
        attribution_model,
        sum(attributed_revenue_usd) as attributed_revenue_usd
    from {{ ref('fct_channel_attribution') }}
    group by attribution_model

)

select
    attributed.attribution_model,
    attributed.attributed_revenue_usd,
    kpi.revenue_usd as kpi_revenue_usd
from attributed
cross join kpi
where abs(attributed.attributed_revenue_usd - kpi.revenue_usd) > 0.0001
