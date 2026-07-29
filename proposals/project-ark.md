# Project Ark — proposed strategy #2 (multi-asset trend & rotation)

*Proposal drafted 2026-07-18. Composite built from the top of the Strategy
Library ranking, designed to diversify — not duplicate — Genesis + Exodus.*

## Why this composite

G+E is a single-stock, US-equity, long-only momentum system. Whatever
diversifies it must bring a **different return driver**, not better stock
picking. Constraints that shaped the choice:

- **Long-only, no margin, no shorting** (rules out pairs/stat-arb/market-neutral).
- **Small capital** (~$570 Schwab, $16 free) — rules out options overlays
  (covered calls need 100-share lots) until the account is much larger.
- **Same infra**: journal.jsonl, control.json kill switch, scheduler, monitor.
- **Different cadence**: G+E works intraday/daily; the complement should be
  slow (monthly) so the two never compete for attention or cash.

The pick: a **multi-asset trend + dual-momentum ETF rotation** — a composite
of the library's #1 (multi-asset trend following, §4.6), #3 (dual momentum,
§4.1.2), #5 (futures-style time-series trend, §10.4 logic on ETFs), and #15
(volatility targeting, §6.5). Ark rides whatever asset class is trending —
equities, bonds, gold, commodities — and retreats to T-bills when nothing is.
Noah's logic: carry every asset class aboard, survive the flood.

## The three engines (mirroring G+E's structure)

### Engine 1 — FLOODGATE (regime & absolute momentum; §4.1.2, §6.5)
- Each candidate ETF must beat T-bills (SGOV total return) on blended
  3/6/12-month momentum, else its slot sits in SGOV. This is the cash
  fallback that made dual momentum #3 in the ranking.
- Portfolio vol target ~10% annualized: scale gross exposure down when
  20-day realized vol of the book runs hot. No leverage ever (cap 100%).
- Crash override: if SPY **and** TLT are both below their 10-month SMA,
  everything goes to SGOV until month-end re-check.

### Engine 2 — TREND (time-series filter; §4.6, §10.4)
Universe (~11 liquid, cheap-per-share ETFs so small capital can hold 4-5):
US large (VOO — SPLG is not offered on Robinhood; verified 2026-07-18),
US small (IJR), intl developed (VEA), emerging (VWO),
long treasuries (TLT), intermediate treasuries (VGIT), IG credit (LQD),
gold (GLDM), broad commodities (DBC), REITs (VNQ), T-bills (SGOV, the
cash seat). All verified fractional-tradable on the Robinhood Agentic
account. Note: fractional orders execute in regular hours only — fine for
Ark's 10:00 ET monthly rebalance. An ETF is *eligible* only if price > 10-month SMA **and**
12-1 month momentum > 0.

### Engine 3 — ROTATE (cross-sectional ranking; §4.1.2)
- Rank eligible ETFs by blended 3/6/12-month momentum.
- Hold the **top 4**, inverse-vol weighted, max 40% in any one asset class.
- Fewer than 4 eligible → unfilled slots stay in SGOV. No forcing.

### Cadence & risk overlay
- **Monthly rebalance** (first trading day, 10:00 ET), one **weekly check**
  (drop anything that has broken 3% below its 10-month SMA mid-month).
  That's it — by design an order of magnitude quieter than G+E.
- Same journal/ledger/control.json pattern; same kill switch semantics;
  registers in the monitor via the existing adapter shape.

## What to expect (honestly)

Faber/Antonacci-style systems of this family have documented long-run
behavior of roughly high-single-digit CAGR with max drawdowns in the 10-20%
range versus 50%+ for buy-and-hold equities — the appeal is the drawdown
profile and the crisis rotation into bonds/gold, not headline return. In a
melt-up it will lag G+E; that's the point of pairing them. No backtest of
this exact spec has been run yet — that's step 1 below.

## Where to run it

Best home: **the Robinhood account** (fractional ETF shares make the math
clean at any capital; the genesis-exodus-scanner skill is already scaffolded
there, halted awaiting broker auth). Workable at Schwab with whole shares
given the low-price share classes chosen, but weights get coarse under
~$1,000 and G+E already owns that account's cash.

## Runner-ups considered and passed on (for now)

- **Covered calls on G+E holdings** (#7) — best infra synergy, blocked by
  capital (needs 100-share lots). Revisit at ~$25k+.
- **Long-only multifactor sleeve** (#2) — overlaps G+E's equity beta too
  much to be the *second* strategy.
- **Pairs/stat-arb** (#10/#14) — needs shorting and margin.

## Backtest results (run 2026-07-18)

Monthly simulation of this exact spec, Aug 2008 – Jun 2026 (~18y), FMP
dividend-adjusted data, 10 bps/side costs. Proxies: GLD→GLDM, IEF→VGIT,
BIL→SGOV. Script: `backtests/ark_backtest.py`; full output incl. equity
curve: `backtests/ark_backtest_results.json`.

| Metric | Ark | SPY buy & hold |
|---|---|---|
| CAGR | **7.3%** | 12.4% |
| Volatility (ann.) | **7.6%** | 15.7% |
| Max drawdown | **-12.7%** | -41.8% |
| Worst month | -5.6% | -16.5% |
| Sharpe (2% rf) | 0.70 | 0.70 |
| $1 becomes | $3.52 | $8.06 |

Reading: the drawdown thesis is confirmed (max DD one-third of SPY's, same
Sharpe at half the vol), and the crash years behave as designed — +6.3% in
the 2008 tail, -3.9% in 2022 (crash override held cash most of that year)
vs SPY -18.2%. The cost is severe lag in V-shaped rebounds (2009: +7% vs
+26%; 2023: -0.5% vs +26%) and a string of flat/negative chop years
(2015 -7.1%, 2016 +2.6%, 2018 -2.2%). Verdict: it earns its seat as
ballast/crisis-alpha next to G+E, not as a return engine. Caveats: monthly
sim only (no weekly check), proxy ETFs, and the strongest known-in-advance
critique — dual momentum's published era (post-2013) contains most of the
weak years, so live expectations should lean toward the 2015-2023 slice,
not the full-period average.

## Next steps

1. ~~Backtest~~ — done, above.
2. ~~Decide account/capital~~ — **approved 2026-07-18: Robinhood, $1,000**
   (book plan: $1k Ark / $1k Babel / $1k G+E). On standby until the user
   funds the account and completes Robinhood MCP auth.
3. Build `ark` as a skill cloned from the G+E scaffold (same state files).
4. Register it in the monitor's `strategies.json` (adapter already fits).
