{#
    Under every attribution model, the credit given to an order's touchpoints
    must add up to exactly the order's revenue, and every order must have
    touchpoints. Returns orders that break either rule.

    The tolerance only absorbs double-precision rounding (around 1e-12). It is
    deliberately far smaller than a cent: a looser tolerance once hid linear
    credits computed with six-decimal fixed-point division, which lost a
    fraction of a cent on every order.
#}

with

orders as (

    select
        order_key,
        revenue_usd
    from {{ ref('int_ga4__orders') }}

),

credited as (

    select
        order_key,
        sum(first_touch_credit * revenue_usd) as first_touch_revenue,
        sum(last_non_direct_credit * revenue_usd) as last_non_direct_revenue,
        sum(linear_credit * revenue_usd) as linear_revenue
    from {{ ref('int_ga4__order_touchpoints') }}
    group by order_key

)

select
    orders.order_key,
    orders.revenue_usd,
    credited.first_touch_revenue,
    credited.last_non_direct_revenue,
    credited.linear_revenue
from orders
left join credited
    on orders.order_key = credited.order_key
where
    credited.order_key is null
    or abs(credited.first_touch_revenue - orders.revenue_usd) > 0.000001
    or abs(credited.last_non_direct_revenue - orders.revenue_usd) > 0.000001
    or abs(credited.linear_revenue - orders.revenue_usd) > 0.000001
