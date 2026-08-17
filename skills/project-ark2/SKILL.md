---
name: project-ark2
description: >-
  Project ARK2 — thematic sleeve (strategy #4). Same deterministic Ark engine, a
  concentrated 4-ETF universe (SMH/XLE/TLT/GLD, top 2 held). Designed to run
  ALONGSIDE Ark, not inside it: sleeve correlation ~0.055 means a 50/50 blend has a
  higher Sharpe (1.12 vs 0.80) and shallower drawdown than folding the same ETFs
  into Ark. Monthly rebalance + weekly trend check. Kill switch in state/control.json.
---

# Project ARK2 — Thematic Sleeve (Robinhood)

Strategy #4. Backtest 2008–2026: **11.77% CAGR, −18.7% maxDD standalone**; blended
50/50 with Ark: **9.74% CAGR, −10.4% maxDD, Sharpe 1.12**. Gauntlet 6/6
(`backtests/ark2_gauntlet.py`).

**This sleeve is volatile on its own — −18.7% drawdown, ~36% losing months.** It is
built to be red while Ark is green; that anti-correlation IS the product. Judge it
blended with Ark, never in isolation.

## ⚠️ ACCOUNT — NOT YET ASSIGNED (BLOCKING)
ARK2 has **no account yet**. As of 2026-08-16 the only agentic-enabled Robinhood
account is **451480438**, which Project Ark owns. ARK2 must NOT share it — two
engines writing targets to one account will fight over the same dollars, exactly the
reason Babel got its own Schwab account.

Before this skill goes live a human must either (a) enable agentic trading on a
second Robinhood account, or (b) open one. Then set the account number here and in
the task prompts, and register it in the monitor.
**Until an account is assigned: compute-only. NEVER place an order.**

## THE ENGINE IS THE AUTHORITY
`python3 scripts/ark2.py targets` computes everything. The agent NEVER overrides,
re-scores, or improvises weights. Engine error (data fragility) -> NO REBALANCE,
report, keep current holdings.

UNIVERSE = SMH (semis), XLE (energy), TLT (treasuries), GLD (gold); **top 2 held**.
TLT is required — the FLOODGATE crash override reads it — and doubles as the
defensive destination alongside GLD. The gauntlet's perturbation test showed the
edge survives dropping any single constituent (dropping SMH entirely still beat Ark
alone), so **the exact tickers are not sacred**; the second uncorrelated sleeve is.

## CADENCE
- **Monthly rebalance** — first TRADING day of the month, ~10:10 ET (staggered off
  Ark's 10:00 so two Claude processes do not start in the same minute).
- **Weekly check** — Fridays ~10:15 ET: `ark2.py weekly-check`; any flagged holding
  (>3% below its 10-mo SMA) is SOLD to SGOV. Sells only — never buys mid-month.

## ORDER MECHANICS (Robinhood MCP)
1. `get_portfolio` — NAV + settled cash. Cash truth: spend only settled funds.
2. Dollar targets = weight × NAV from `state/ark2_targets.json`.
3. DRIFT BAND: trade only legs differing by >2% of NAV; always trade new entries and
   full exits.
4. SELLS FIRST, then buys. Fractional NOTIONAL orders (Robinhood supports these;
   Schwab does not — this sleeve is Robinhood-only for that reason).
5. `review_equity_order` before EVERY placement; warning -> skip that order, log, alert.
6. FILL TRUTH: confirm each fill via `get_equity_orders` before relying on freed cash.
7. NO margin, NO shorting, NO options. Cap total invested at 100% — never borrow.
8. SGOV weight is implemented by BUYING SGOV (it is the cash seat, not idle cash).

## REBALANCING AGAINST ARK
The 1.12 Sharpe assumes the two sleeves are periodically rebalanced back toward
50/50. That is a HUMAN decision, not an automated transfer — this skill never moves
money between accounts. Review the split when the sleeves drift past roughly 60/40.

## KILL SWITCH & SAFETY
`python3 scripts/ops.py status` before any orders — halted=true -> monitoring only.
Data fragility (engine error, quote moved >3% vs targets basis, missing fills) ->
stop, report, never improvise. HUMAN-ONLY: `ops.py ack-losses`, `ops.py resume`.

## JOURNAL
Append one JSON line per run to `state/journal.jsonl` (resolve the path relative to
this skill directory — do NOT hardcode /Users or /home; runs on both Mac and the
Linux server). Keys: "ts" (ISO-8601 WITH local offset), "run_type":
"rebalance"|"weekly_check", nav, cash, targets, orders, fills, positions, decision.
After a completed rebalance append the realized prior-month return to
`state/ark2_history.json` (the engine's vol-target input): {"month": "YYYY-MM",
"ret": <decimal>}.

## MONITOR
Strategy id "project-ark2" in AI_Trading/strategy-monitor/config/strategies.json.
Cadence is monthly/weekly like Ark, so its stale threshold is 7+ days, not hours.
Deposits are recorded by the human/main session — never edit deposits yourself.
