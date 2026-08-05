---
name: project-babel
description: >-
  Project Babel — gated 3x leveraged rotation on Schwab (satellite strategy #3, the
  aggressive sleeve). Weekly ladder decides 3x / 1x / cash from a 200-DMA + 20d-vol
  governor on QQQ or SPY (whichever leads on 63/126-day momentum); a daily breaker
  de-levers to SGOV on any trend or vol breach. Fully deterministic signals from
  scripts/babel.py; the agent only translates the target into orders. Trades ONLY
  Schwab account 20425301. Kill switch in state/control.json.
---

# Project Babel — Gated Leveraged Rotation (Schwab)

The aggressive satellite. Backtest 1999–2026 (v2): **15.2% CAGR, −52.2% maxDD**,
$1 → $42.13 vs QQQ's $9.24. Raw 3x buy-and-hold LOST money over the same period
(−99.98% maxDD) — **the governor is the entire strategy**, not the leverage.

A ~50% drawdown is pre-accepted, not a malfunction. Expect whipsaw years that lose
money while the index rises (2005: −17% vs QQQ +1.6%). Judge it over years, not weeks.

## ACCOUNT — HARD WHITELIST
Schwab account **20425301** ONLY. Refuse to act on any other account.
NEVER touch Genesis+Exodus's Schwab account (…3393) or Ark's Robinhood account (…0438).
The whitelist is enforced in `state/schwab.env` (`SCHWAB_TRADING_ACCOUNT`); `schwab.py`
exits ACCOUNT_ACCESS_ERROR if the account is missing or mismatched. Never edit that value.

## THE ENGINE IS THE AUTHORITY
`python3 scripts/babel.py target` computes the SELECTOR + GOVERNOR per the validated
backtest. The agent NEVER overrides the tier, picks a different vehicle, sizes above
the tier, or averages down. Engine error (data fragility) -> NO TRADE, report, hold.

**Governor ladder** (signals on the UNDERLYING index, never the LETF):
| Condition on leader | Tier | Holding |
|---|---|---|
| price > 200-DMA and 20d vol < 20% | **3x** | TQQQ (QQQ) / UPRO (SPY) |
| price > 200-DMA and vol 20–35% | **1x** | ⅓ TQQQ/UPRO + ⅔ SGOV |
| price < 200-DMA or vol > 35% | **cash** | 100% SGOV |

**Selector**: blended 63/126-day momentum picks QQQ vs SPY. One index at a time.

## CADENCE
- **Weekly ladder** — Fridays ~15:45 ET compute, execute at Monday's open (~09:45 ET).
  This is the ONLY time the strategy may increase exposure or switch leaders.
- **Daily breaker** — every market day ~09:50 ET: `babel.py daily-check`.
  It may ONLY de-lever to SGOV. It never re-levers, never switches leaders mid-week.
  A missed breaker run is Babel's core tail risk — the watchdog must stay green.

## ORDER MECHANICS (Schwab)
1. `python3 scripts/ops.py status` — halted -> monitoring only, no orders.
2. `python3 scripts/schwab.py positions` — cash truth + current holdings.
3. Compute dollar targets = weight × NAV from `state/babel_target.json`.
4. **NO-BORROW GUARD (this is a MARGIN account)**: size every order against SETTLED CASH
   only, never buying power. Total invested must never exceed 100% of NAV. If the API
   reports buying power > cash, ignore buying power entirely. Never short, no options.
5. SELLS FIRST, then buys. WHOLE shares only (Schwab has no fractional equity orders) —
   round DOWN; the residual stays in cash. Never round up into a leveraged position.
6. `schwab.py preview-order` before EVERY placement; any warning -> skip, log, alert.
7. FILL TRUTH: confirm each fill via `schwab.py orders filled` before relying on freed cash.
8. Drift band: skip a rebalance leg if the position is already within 5% of NAV of target
   (whole-share granularity on ~$1k makes finer targeting meaningless churn).
9. ROUNDING SLOP is expected and acceptable at this account size (measured 2026-08-04 at
   TQQQ $74.58 / SGOV $100.44): 3x tier invests ~97% of NAV, 1x ~90%, cash tier ~90% with
   the remainder sitting as literal cash. Never round UP or add a share to close the gap —
   idle cash is the safe error, over-exposure is not. Residual cash in the cash tier is
   economically equivalent to SGOV, so do not chase it.

## KILL SWITCH & SAFETY
`state/control.json` — `halted: true` stops all trading. Data fragility (engine error,
quote >3% from the signal basis, missing fills, stale data date) -> stop, report, never
improvise. Consecutive-loss and daily-loss breakers do NOT apply here: the governor is
the risk control, and a −50% drawdown is within design. HUMAN-ONLY: `ops.py resume`.

## JOURNAL
Append one JSON line per run to `state/journal.jsonl` (resolve the path relative to this
skill directory — do NOT hardcode /Users or /home paths; the skill runs on both Mac and
the Linux server). Keys: "ts" (ISO-8601 WITH local offset), "run_type":
"weekly_ladder"|"daily_check", tier, leader, nav, cash, target_weights, orders, fills,
positions, decision. Also append each weekly decision to `state/babel_history.jsonl`.

## MONITOR
Strategy id "project-babel" in AI_Trading/strategy-monitor/config/strategies.json.
Deposits are recorded there by the human/main session — never edit deposits yourself.
Babel's heartbeat cadence is DAILY (breaker), so its stale threshold is tighter than Ark's.
