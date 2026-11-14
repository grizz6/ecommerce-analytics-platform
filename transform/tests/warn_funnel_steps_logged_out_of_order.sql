{{ config(severity='warn') }}

{#
    Flags sessions that logged a funnel step without the step before it.

    This is a warning, not an error: GA4 does not guarantee that every
    purchase has its earlier steps logged (ad blockers, consent settings,
    direct links to checkout and tag gaps all cause it). Such sessions are
    kept. fct_funnel_daily uses a closed funnel so step rates stay valid, and
    counts every purchase in purchase_sessions_any. The warning keeps the
    size of the gap visible on every run.
#}

select
    session_key,
    has_view_item,
    has_add_to_cart,
    has_begin_checkout,
    has_add_shipping_info,
    has_add_payment_info,
    has_purchase
from {{ ref('int_ga4__session_funnel') }}
where
    (has_add_to_cart and not has_view_item)
    or (has_begin_checkout and not has_add_to_cart)
    or (has_add_shipping_info and not has_begin_checkout)
    or (has_add_payment_info and not has_add_shipping_info)
    or (has_purchase and not has_add_payment_info)
