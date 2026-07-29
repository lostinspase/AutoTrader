# FMP API Reference — endpoints used by scripts/fmp.py

All calls go through `scripts/fmp.py`, which reads the key from `state/fmp.env` (NEVER print the key).
Base: `https://financialmodelingprep.com/stable`. Responses are daily-cached under `state/cache/`
(~20h TTL) to keep API usage cheap. A paid Premium/Stable plan is assumed; the free tier will not
cover all of these.

The CLI never raises on a network failure — it returns an `{"error": …}` dict (or an empty list for
screener/movers). Callers MUST gate any name with an error to WATCHLIST/NO TRADE.

---

## Commands -> endpoints

| `fmp.py` command        | FMP endpoint(s)                                  | Notes |
|-------------------------|--------------------------------------------------|-------|
| `regime`                | `historical-price-eod/full` (SPY/QQQ/IWM), `quote` (^VIX) | computes class normal/cautious/defensive/crash |
| `screener [k=v …]`      | `company-screener`                               | US, non-ETF, non-fund, liquid; primary discovery |
| `movers`                | `biggest-gainers`, `biggest-losers`, `most-actives` | losers feed the Exodus rebound engine |
| `indicators SYM`        | `historical-price-eod/full`                      | all technical levels computed locally |
| `earnings SYM`          | `earnings-calendar`                              | binary-event guard |
| `earnings-multi SYM…`   | `earnings-calendar` (per symbol)                 | sweep all holdings |
| `news SYM…`             | `news/stock`                                     | advisory catalyst sensor |
| `rs SYM`                | `historical-price-eod/full` (+SPY)               | blended RS excess vs SPY (21/63/126d) |
| `correlation SYM…`      | `historical-price-eod/full` (per symbol)         | avg pairwise return correlation |
| `breadth`               | `historical-price-eod/full` (sector ETFs)        | % sector ETFs above 50-DMA |
| `rotation SYM…`         | (uses `rs`)                                       | leaderboard + rotation-out flags |
| `pricechange SYM…`      | `quote`                                           | quick % change |
| `scores SYM`            | `financial-scores`                                | advisory |
| `float SYM`             | `shares-float`                                     | advisory |
| `insider SYM`           | `insider-trading/search`                          | advisory |
| `grades SYM`            | `grades`                                           | advisory |
| `sectors`               | `sector-performance-snapshot`                     | advisory |

---

## screener parameters (pass as `k=v` args)

`marketCapMoreThan`, `marketCapLowerThan`, `priceMoreThan`, `priceLowerThan`, `volumeMoreThan`,
`exchange`, `sector`, `limit`. Defaults applied by `fmp.py`: marketCap>=$2B, price>=$5,
volume>=500k, country=US, isEtf=false, isFund=false, isActivelyTrading=true, limit=100.

Example: `fmp.py screener "priceMoreThan=10" "priceLowerThan=50" "limit=120"` — useful for this
account, since names under ~$50 are the ones whose 2 whole shares can fit the $100 cap.

---

## indicators SYM — returned fields

`price, sma50, sma150, sma200, sma200_rising, hi52, lo52, pct_from_hi, pct_from_lo, breakout20,
breakout55, atr20, atr14, ret63d, rs_vs_spy, genesis_trend_template_pass, avgDollarVol20,
fiftytwo_week_complete, history_days`.

52-week levels are NULL unless `history_days >= 252` — a deliberate guard so a short history can't
fake a 52-week high/low. The trend template fails by construction when `fiftytwo_week_complete` is false.

---

## Plan / quota notes

- Histories are the heaviest calls; the daily cache (`state/cache/`) keeps repeated scans cheap.
- If you hit rate limits, widen the cache TTL in `fmp.py` (`CACHE_TTL_SECONDS`) or reduce candidate count.
- A `_http_error: 401/403` means a bad/missing key or a plan that doesn't include the endpoint.
- A `_http_error: 429` means rate-limited — back off; the affected names gate to WATCHLIST that scan.
