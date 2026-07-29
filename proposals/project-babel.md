# Project Babel — proposed strategy #3 (aggressive leveraged rotation)

*Proposal drafted 2026-07-18. Objective: materially higher returns than G+E
and Ark, accepting materially higher risk. The name is the warning label.*

## Design logic

A long-only small account has three aggression levers: leverage, concentration,
or crypto. Babel uses **leverage with a regime governor** — the one approach of
the three with a documented mechanism for surviving its own failure mode:

- Raw 3x ETFs buy-and-hold is uninvestable (volatility decay + a 2000-02 or
  2008 event is a >95% drawdown).
- But leverage *conditioned on trend and volatility* — 3x only while the
  underlying index is above its 200-day MA in a calm-vol regime — has strong
  practitioner literature (Gayed, "Leverage for the Long Run"): the 200-DMA
  gate historically sidesteps the fat left tail, because crashes overwhelmingly
  happen below trend and in high vol.
- Library lineage: §4.5 (LETFs) + §3.11 (MA timing) + §4.1.2 (dual momentum)
  + §6.5 (vol targeting).

## The three engines

### Engine 1 — GOVERNOR (regime ladder; the whole strategy is this gate)
Signals computed on the UNDERLYING index (QQQ/SPY), never on the LETF:
- Price > 200-DMA **and** 20-day realized vol < 20% ann. → **3x** (TQQQ/UPRO)
- Price > 200-DMA and vol 20–35% → **1x** (QQQ/SPY)
- Price < 200-DMA **or** vol > 35% → **cash** (SGOV)

### Engine 2 — SELECTOR (dual momentum)
Blended 3/6-month momentum picks the leader between QQQ and SPY; Babel holds
one index at a time at whatever leverage tier the governor allows.

### Engine 3 — CADENCE (weekly)
Signals evaluated at the last close of each week, positions changed at the
next session. Weekly (not monthly) because at 3x, exit speed is survival;
not daily because whipsaw costs compound at 3x too.

### Risk rules
- Never sized above the governor tier; no averaging down; no overrides.
- Same journal/control.json/kill-switch infra as G+E and Ark.
- Position sizing at deployment: Babel gets only capital whose full loss is
  acceptable — treat it as the book's satellite, never the core.

## Expected failure modes (stated up front)

- **Whipsaw years** (choppy, trendless): repeated 3x→cash→3x switches each
  cost slippage; expect mid-teens drawdowns with nothing to show.
- **Gap risk**: an overnight crash from above-trend calm (Oct-1987-shaped)
  hits at full 3x before the weekly gate can react. This tail cannot be
  hedged away without options; it is the price of the strategy.
- **Decay drag** in sideways-volatile markets held at 3x.

## Backtest results (run 2026-07-18)

Daily simulation, Dec 1999 – Jul 2026 (26.6y, dot-com and GFC included).
3x ETFs simulated (0.95% ER + 2x cash-rate financing); simulator validated
against real TQQQ 2011-2026 (sim 41.5% CAGR vs real 39.9% — sim runs ~1.7%/yr
hot, shave expectations accordingly). 5 bps/switch. Script:
`backtests/babel_backtest.py`; full output: `babel_backtest_results.json`.

v2 (weekly ladder + daily emergency de-lever, matching our daily quick-check
infra) is the recommended variant:

| Metric | Babel v2 | QQQ B&H | SPY B&H | Raw 3x QQQ B&H |
|---|---|---|---|---|
| CAGR | **15.2%** | 8.8% | 8.3% | -1.6% |
| Max drawdown | **-52.2%** | -83.0% | -55.2% | -99.98% |
| Worst day | -15.2% | -12.0% | -10.9% | -36.0% |
| Sharpe (2% rf) | 0.52 | 0.37 | 0.41 | 0.36 |
| $1 becomes | **$42.13** | $9.24 | $8.23 | $0.65 |

Reading:
- **The governor is the entire strategy**: raw 3x buy-and-hold *lost* money
  over 26 years (-99.98% max DD); the same exposure behind the trend/vol gate
  compounded at 15.2%.
- Dot-com validation: +7.6%/+4.0%/-12.2% (v1) across 2000-02 while QQQ lost
  36%/33%/37% — the gate sidesteps slow-grind bears almost entirely.
- The daily breaker (v2) is what tames fast crashes: 2011 -41%→-27%,
  2018 -28.5%→-15.9%. 2022 stayed ~-28% either way (pure chop).
- **The cost is real**: ~-50% drawdowns twice (2021-22 peak-to-trough; the
  2004-08 grind), five negative years including whipsaw losses in years when
  the index was UP (2005: -17% vs QQQ +1.6%). ~10 switches/year = short-term
  capital gains in a taxable account.

Verdict vs the other two strategies: roughly double Ark's CAGR and ~4x its
drawdown. Fits only as a satellite sleeve — capital whose 50% drawdown is
pre-accepted — never the core.

## Deployment decisions (2026-07-18)

- **Venue: a NEW, dedicated Schwab brokerage account** (not G+E's account —
  its scanner treats account-level cash as deployable, and Babel parks in
  cash by design; separate accounts keep the two brains from fighting over
  the same dollars). The new account number gets whitelisted in the Babel
  skill only.
- **Capital: $1,000** (user decision; book funded as $1k Babel / $1k Ark /
  $1k G+E — Babel at ~1/3 of book, above the satellite guideline, accepted).
- **1x-tier implementation: ⅓ TQQQ + ⅔ SGOV** instead of holding QQQM/SPLG
  outright — equivalent exposure at weekly rebalance, and it keeps every
  share in the strategy under ~$101 (TQQQ $67.53, SGOV $100.58 at decision
  time), so $1k granularity stays workable (~7% rounding slop).
- **Hard precondition before capital**: scheduler hardening. G+E's scheduler
  reliability has averaged ~35%; a missed daily de-lever check is Babel's
  tail risk. Needs a reliable daily breaker job + a watchdog alert when a
  scheduled check does not run.

## Status

- [x] Backtest — done, above. v2 (daily breaker) recommended.
- [x] Venue + capital decided (Schwab dedicated account, $1,000).
- [ ] Scheduler hardening + missed-run watchdog (blocking).
- [x] New Schwab account opened: **2042-5301** (user, 2026-07-18). $1,000
      incoming.
- [ ] Re-auth Schwab OAuth (refresh token expires 2026-07-22) and **include
      account 2042-5301 on the consent screen** so the API can see it —
      consent predates the account. Verify visibility after re-auth.
      (2026-07-18: account-data endpoints 500ing — likely weekend
      maintenance; quotes fine. Re-check before Monday open for G+E's sake.)
- [ ] Build `babel` skill whitelisted to 2042-5301 only; register in monitor.
