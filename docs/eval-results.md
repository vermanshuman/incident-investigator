# Eval results

_Generated 2026-10-11 05:12 UTC · model `unknown` · replayed from cassettes_

**Mean score 0.83** over 6 scored runs (stdev 0.20) · root cause category right 5/6 · culprit right 3/6 · external call right 6/6

Cost $0.0000 total · 7.7 model calls and 0.1s per run on average.

| case | score | category | culprit | external | cites | steps | calls | tokens | $ | s |
|---|---|---|---|---|---|---|---|---|---|---|
| s01_null_check_v1 | 0.75 | ok | **x** | ok | ok | 2 | 6 | 10776 | 0.0000 | 0.0 |
| s03_pool_exhaustion_v1 | 0.75 | ok | **x** | ok | ok | 2 | 6 | 11620 | 0.0000 | 0.1 |
| s04_rotated_key_v1 | 1.00 | ok | ok | ok | ok | 5 | 9 | 19096 | 0.0000 | 0.1 |
| s05_n_plus_one_v1 | 1.00 | ok | ok | ok | ok | 4 | 8 | 14870 | 0.0000 | 0.1 |
| s07_feature_flag_v1 | 0.50 | **x** | **x** | ok | ok | 4 | 8 | 15224 | 0.0000 | 0.1 |
| s08_provider_outage_v1 | 1.00 | ok | ok | ok | ok | 5 | 9 | 17927 | 0.0000 | 0.1 |

## What each run concluded

| case | expected | agent said | root cause |
|---|---|---|---|
| s01_null_check_v1 | bad_deploy | bad_deploy | Deploy 64dfbac6b312 removed backend validation for shipping_address assuming client enforcement, leading to unhandled AttributeError: 'NoneT |
| s03_pool_exhaustion_v1 | resource_config | resource_config | Deploy e07160514c26 reduced the SQLAlchemy QueuePool size to 1 with 0 overflow and a 1-second timeout, exhausting available connections unde |
| s04_rotated_key_v1 | config_secret | config_secret | The payment provider API key used by the checkout service has expired or been revoked externally, causing payments.example.com to reject pay |
| s05_n_plus_one_v1 | performance | performance | Commit 51178094 introduced an N+1 query pattern in app/routers/checkout.py, executing db.get() and db.refresh() on Product for every cart it |
| s07_feature_flag_v1 | config | bad_deploy | Commit 3b58c31d enabled flag_tax_v2_regions for 'in-south' and 'eu-central', but the tax v2 implementation lacks regional dictionary keys fo |
| s08_provider_outage_v1 | external | external | The external payment provider payments.example.com is unresponsive or experiencing high latency, causing payment requests to time out after  |

## What is scored

- **category** - the confirmed hypothesis is in the right class of cause
- **culprit** - the report cites the file or config that actually caused it, which means it read the change rather than trusting the commit message
- **external** - the agent correctly said whether this was our bug
- **cites** - the claims rest on evidence a tool really returned

Failures are kept in the table on purpose: a suite that always passes is not measuring.
