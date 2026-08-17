---
name: project-ark
description: >-
  Project Ark — multi-asset trend + dual-momentum ETF rotation on Robinhood (ballast
  strategy #2, diversifies Genesis+Exodus). Monthly rebalance + weekly trend check across
  ~11 ETFs with SGOV cash fallback, 10% vol target, and SPY+TLT crash override. Fully
  deterministic signals from scripts/ark.py; the agent only translates targets to orders.
  Trades ONLY Robinhood account 451480438. Kill switch in state/control.json.
---

# Project Ark — Multi-Asset Trend & Rotation (Robinhood)

Ballast, not a return engine. Backtest 2008–2026: 7.3% CAGR, −12.7% maxDD, +6.3% in 2008.
Expect it to LAG in melt-ups — that is the design. Judge it on drawdowns and crisis years.

## ACCOUNT — HARD WHITELIST
Robinhood account **451480438** ONLY (the agentic account). Refuse to act on any other
account. NEVER touch Schwab accounts (Genesis owns …3393, Babel owns …5301).

## THE ENGINE IS THE AUTHORITY
`python3 scripts/ark.py targets` computes everything (FLOODGATE/TREND/ROTATE per the
validated backtest). The agent NEVER overrides, re-scores, or improvises weights. If the
engine returns an error (data fragility) -> NO REBALANCE, report, keep current holdings.

UNIVERSE = 10 ETFs. SMH/XLE are deliberately NOT here — they live in Project ARK2, a
separate sleeve. Folding them in tested well (Sharpe 0.80) but splitting tested better
(blend Sharpe 1.12, drawdown -10.4% vs -12.9%) because a second engine ADDS exposure
instead of displacing VOO/VEA for the same 4 slots. Never re-add them while ARK2 runs.

## CADENCE
- **Monthly rebalance** — first TRADING day of the month, ~10:00 ET (fractional orders
  are regular-hours only). Task fires days 1–4; execute only if today is the month's
  first trading day, else output "not first trading day — no action."
- **Weekly check** — Fridays ~10:05 ET: `ark.py weekly-check`; any flagged holding
  (>3% below its 10-mo SMA) is SOLD to SGOV. Sells only — never buys mid-month.
- Initial allocation counts as the first rebalance (any trading day, once cash settles).

## ORDER MECHANICS (Robinhood MCP)
1. `get_portfolio` (451480438) — NAV + settled cash. Cash-truth: spend only settled funds.
2. Compute dollar targets = weight × NAV from state/ark_targets.json.
3. DRIFT BAND: trade only positions whose current vs target weight differs by >2% of NAV
   (avoids churn); always trade new entries and full exits.
4. SELLS FIRST, then buys (frees cash). Fractional NOTIONAL orders (dollar amounts).
5. `review_equity_order` before EVERY placement; if it warns -> skip that order, log, alert.
6. FILL TRUTH: confirm each order filled via get_equity_orders before relying on freed cash.
7. NO margin, NO shorting, NO options, NO crypto. Cap total invested at 100% — never borrow.
8. SGOV weight is implemented by BUYING SGOV (it is the cash seat, not idle cash).

## KILL SWITCH & SAFETY
`python3 scripts/ops.py status` before any orders — halt=true -> monitoring only.
Data fragility (engine error, quote moved >3% vs targets basis, missing fills) -> stop,
report, never improvise. This account holds ~$1k; a full rebalance is ~8 small orders.

## JOURNAL
Append one JSON line per run to the ABSOLUTE path
/Users/jp/.claude/skills/project-ark/state/journal.jsonl with "ts" (ISO-8601 WITH local
offset), "run_type": "rebalance"|"weekly_check", nav, targets, orders placed, fills,
decision. After a completed rebalance, also append the realized prior-month portfolio
return to state/ark_history.json (the engine's vol-target input): {"month": "YYYY-MM",
"ret": <decimal>} computed from prior targets and month-end NAV change.

## MONITOR
Strategy id "project-ark" in AI_Trading/strategy-monitor/config/strategies.json.
Deposits are recorded there by the human/main session — never edit deposits yourself.
