{#
    GA4 default channel group, applied to a source, medium and campaign.

    Follows Google's published rule order for the default channel group.
    Simplifications, documented in docs/decisions/0004-channel-grouping.md:
    the source category seed lists common sources only, rules that rely on
    click identifiers or Google Ads auto-tagging are not reproduced, and
    obfuscated values such as "(data deleted)" or "<Other>" fall through to
    Unassigned.

    source_category is the category from the ga4_source_categories seed, or
    null when the source is not listed.
#}
{% macro default_channel_group(source, medium, campaign, source_category) -%}
    {%- set src = "lower(coalesce(" ~ source ~ ", ''))" -%}
    {%- set med = "lower(coalesce(" ~ medium ~ ", ''))" -%}
    {%- set cmp = "lower(coalesce(" ~ campaign ~ ", ''))" -%}
    {%- set cat = "coalesce(" ~ source_category ~ ", '')" -%}
    {%- set paid_medium = regex_full_match(med, '(.*cp.*|ppc|retargeting|paid.*)') -%}
    {%- set shopping_campaign = regex_full_match(cmp, '(.*(([^a-df-z]|^)shop|shopping).*)') -%}
    case
        when {{ src }} = '(direct)' and {{ med }} in ('(not set)', '(none)') then 'Direct'
        when {{ cmp }} like '%cross-network%' then 'Cross-network'
        when ({{ cat }} = 'SHOPPING' or {{ shopping_campaign }}) and {{ paid_medium }}
            then 'Paid Shopping'
        when {{ cat }} = 'SEARCH' and {{ paid_medium }} then 'Paid Search'
        when {{ cat }} = 'SOCIAL' and {{ paid_medium }} then 'Paid Social'
        when {{ cat }} = 'VIDEO' and {{ paid_medium }} then 'Paid Video'
        when {{ med }} in ('display', 'banner', 'expandable', 'interstitial', 'cpm')
            then 'Display'
        when {{ paid_medium }} then 'Paid Other'
        when {{ cat }} = 'SHOPPING' or {{ shopping_campaign }} then 'Organic Shopping'
        when
            {{ cat }} = 'SOCIAL'
            or {{ med }} in (
                'social', 'social-network', 'social-media', 'sm', 'social network', 'social media'
            )
            then 'Organic Social'
        when {{ cat }} = 'VIDEO' or {{ med }} like '%video%' then 'Organic Video'
        when {{ cat }} = 'SEARCH' or {{ med }} = 'organic' then 'Organic Search'
        when {{ med }} in ('referral', 'app', 'link') then 'Referral'
        when
            {{ regex_full_match(src, '(email|e-mail|e_mail|e mail)') }}
            or {{ regex_full_match(med, '(email|e-mail|e_mail|e mail)') }}
            then 'Email'
        when {{ med }} = 'affiliate' then 'Affiliates'
        when {{ med }} = 'audio' then 'Audio'
        when {{ src }} = 'sms' or {{ med }} = 'sms' then 'SMS'
        when
            {{ med }} like '%push'
            or {{ med }} like '%mobile%'
            or {{ med }} like '%notification%'
            or {{ src }} = 'firebase'
            then 'Mobile Push Notifications'
        else 'Unassigned'
    end
{%- endmacro %}
