# 0004. Channel grouping

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Revenue and funnel questions are asked by acquisition channel. GA4 assigns
channels with its default channel group, a set of ordered rules over source,
medium, campaign and a "source category" list Google maintains. The public
sample predates the export's session-level channel fields, so channels must be
derived in dbt.

## Decision

- The `default_channel_group()` macro applies Google's published rules in
  Google's order: Direct, Cross-network, Paid Shopping, Paid Search, Paid
  Social, Paid Video, Display, Paid Other, Organic Shopping, Organic Social,
  Organic Video, Organic Search, Referral, Email, Affiliates, Audio, SMS,
  Mobile Push Notifications, then Unassigned.
- The `ga4_source_categories` seed maps common sources to SEARCH, SOCIAL,
  VIDEO or SHOPPING. Because rule order matters, `facebook.com / referral` is
  Organic Social, not Referral, exactly as in GA4.
- Channels are assigned per session, from the session's source, medium and
  campaign. A session with no traffic parameters is `(direct) / (none)`,
  which is Direct.

## Simplifications

- The seed covers common sources only, not Google's full list. Unlisted
  sources fall back to the medium-based rules.
- Rules that depend on Google Ads auto-tagging or click identifiers (gclid,
  dclid) are not reproduced.
- Obfuscated values (`(data deleted)`, `<Other>`, empty string) match no rule
  and become Unassigned. The share of Unassigned sessions is therefore a
  property of the sample, not of the store's real traffic, and is reported as
  a limitation.

## Consequences

- Channel results are comparable with GA4's own reports for the sources the
  seed covers.
- Adding a source category is a one-line seed change with no model change.
