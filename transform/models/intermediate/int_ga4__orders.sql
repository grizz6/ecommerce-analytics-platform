{#
    One row per order, built from purchase events.

    - A valid transaction id (not null, not empty, not "(not set)") identifies
      the order. When the same transaction id is logged more than once, for
      example on a page reload, the first purchase event is kept and the rest
      are counted in purchase_event_count.
    - A purchase without a valid transaction id cannot be matched to other
      events, so each such event is its own order, flagged with
      has_valid_transaction_id = false. Its revenue is kept, not dropped.
#}

with

purchases as (

    select
        event_key,
        user_pseudo_id,
        session_key,
        event_ts_utc,
        reporting_date,
        transaction_id,
        purchase_revenue_usd,
        tax_value_usd,
        shipping_value_usd,
        total_item_quantity,
        unique_items
    from {{ ref('stg_ga4__events') }}
    where event_name = 'purchase'

),

item_totals as (

    select
        event_key,
        sum(quantity) as item_quantity
    from {{ ref('stg_ga4__items') }}
    where event_name = 'purchase'
    group by event_key

),

classified as (

    select
        purchases.event_key,
        purchases.user_pseudo_id,
        purchases.session_key,
        purchases.event_ts_utc,
        purchases.reporting_date,
        purchases.transaction_id,
        purchases.purchase_revenue_usd,
        purchases.tax_value_usd,
        purchases.shipping_value_usd,
        purchases.unique_items,
        coalesce(purchases.total_item_quantity, item_totals.item_quantity) as item_quantity,
        coalesce(
            purchases.transaction_id is not null
            and trim(purchases.transaction_id) not in ('', '(not set)'),
            false
        ) as has_valid_transaction_id
    from purchases
    left join item_totals
        on purchases.event_key = item_totals.event_key

),

identified as (

    select
        *,
        case
            when has_valid_transaction_id then 'transaction:' || transaction_id
            else 'event:' || event_key
        end as order_source_id
    from classified

),

ranked as (

    select
        *,
        row_number() over (
            partition by order_source_id
            order by event_ts_utc, event_key
        ) as purchase_event_number,
        count(*) over (partition by order_source_id) as purchase_event_count
    from identified

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['order_source_id']) }} as order_key,
        transaction_id,
        has_valid_transaction_id,
        purchase_event_count,
        event_key as purchase_event_key,
        user_pseudo_id,
        session_key,
        event_ts_utc as order_ts_utc,
        reporting_date as order_date,
        coalesce(purchase_revenue_usd, 0) as revenue_usd,
        coalesce(tax_value_usd, 0) as tax_usd,
        coalesce(shipping_value_usd, 0) as shipping_usd,
        coalesce(item_quantity, 0) as item_quantity,
        coalesce(unique_items, 0) as unique_items
    from ranked
    where purchase_event_number = 1

)

select * from final
