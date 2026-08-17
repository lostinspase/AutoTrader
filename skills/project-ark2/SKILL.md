---
name: project-ark2
description: >-
  Project ARK2 — thematic sleeve (strategy #4). Same deterministic Ark engine, a
  concentrated 4-ETF universe (SOXQ/XLE/TLT/GLDM, top 2 held). Designed to run
  ALONGSIDE Ark, not inside it: sleeve correlation ~0.04 means a 50/50 blend has a
  higher Sharpe (1.12 vs 0.80) and shallower drawdown than folding the same ETFs
  into Ark. Monthly rebalance + weekly trend check on SCHWAB (whole shares). Kill switch in state/control.json.
---

# Project ARK2 — Thematic Sleeve (Schwab)

Strategy #4. Backtest 2008–2026 (on the SOXX/GLD long-history proxies): **11.76%
CAGR, −13.3% maxDD standalone**; blended 50/50 with Ark: **9.75% CAGR, −9.9% maxDD,
Sharpe 1.12** vs Ark alone at 0.70. Gauntlet 6/6
(`backtests/ark2_schwab_gauntlet.py` — the Schwab-tradeable config; the earlier
`ark2_gauntlet.py` tested the Robinhood SMH/GLD version and is superseded).

**This sleeve is volatile on its own — −13.3% drawdown, ~36% losing months.** It is
built to be red while Ark is green; that anti-correlation IS the product. Judge it
blended with Ark, never in isolation.

## ⚠️ ACCOUNT — NOT YET ASSIGNED (BLOCKING)
ARK2 trades on **SCHWAB**, not Robinhood. Robinhood permits only one agentic account
per login and has no agentic sub-accounts, and Project Ark owns that one (451480438);
two engines writing targets to one account would fight over the same dollars. Schwab
already proves the alternative — Genesis (…3393) and Babel (…5301) run independently
under a single OAuth grant, each pinned to its own account.

**Before this skill can trade, a human must:**
1. Open a THIRD Schwab brokerage account.
2. Re-auth Schwab so the new account enters the OAuth grant (the account list only
   refreshes on re-auth — this is how Babel's account first appeared).
3. Set the real number in BOTH `scripts/schwab.py` (`ARK2_ACCOUNT`, currently the
   `<UNASSIGNED>` placeholder) and `state/schwab.env` (`SCHWAB_TRADING_ACCOUNT`).
   They must match or every call fails closed — that is the guard, not a nuisance.
4. Write the two task prompts, add crons, fund ~$1,000, set `halted: false`.

**Until then: compute-only. The engine computes targets fine; every broker call
refuses.** Do NOT point this skill at …3393 or …5301.

## THE ENGINE IS THE AUTHORITY
`python3 scripts/ark2.py targets` computes everything. The agent NEVER overrides,
re-scores, or improvises weights. Engine error (data fragility) -> NO REBALANCE,
report, keep current holdings.

UNIVERSE = **SOXQ** (semis), **XLE** (energy), **TLT** (treasuries), **GLDM** (gold);
**top 2 held**. TLT is required — the FLOODGATE crash override reads it — and doubles
as the defensive destination alongside GLDM. The gauntlet's perturbation test showed
the edge survives dropping any single constituent (dropping semis entirely still beat
Ark alone), so **the exact tickers are not sacred**; the second uncorrelated sleeve is.

TICKERS ARE CHOSEN FOR WHOLE-SHARE SIZING, not preference. Schwab has no fractional
equity orders, and at $1k NAV a 35% weight in SMH ($588), SOXX ($550) or GLD ($401)
buys ZERO shares — the leg would silently vanish. SOXQ ($98) and GLDM ($87) size
cleanly. The backtest runs on long-history proxies (SOXX→SOXQ, GLD→GLDM; fidelity
0.993 and 0.9991) because SOXQ only lists from 2021.

## CADENCE
- **Monthly rebalance** — first TRADING day of the month, ~10:10 ET (staggered off
  Ark's 10:00 so two Claude processes do not start in the same minute).
- **Weekly check** — Fridays ~10:15 ET: `ark2.py weekly-check`; any flagged holding
  (>3% below its 10-mo SMA) is SOLD to SGOV. Sells only — never buys mid-month.

## ORDER MECHANICS (Schwab)
1. `python3 scripts/ops.py status` — halted -> monitoring only, no orders.
2. `python3 scripts/schwab.py positions` — cash truth + current holdings.
3. Dollar targets = weight × NAV from `state/ark2_targets.json`.
4. **WHOLE SHARES ONLY — round DOWN, never up.** Residual cash is expected (~15% at
   $1k) and is the SAFE error; never add a share to close the gap.
5. A **SGOV leg that rounds to 0 shares is fine** — leave it as literal cash. Cash and
   SGOV are economically equivalent here; do not force a purchase to satisfy the target.
6. Size against **SETTLED CASH**, never buying power. NO margin, NO shorting, NO options.
7. SELLS FIRST, then buys. `schwab.py preview-order` before EVERY placement (build with
   `schwab.py build-order --symbol X --side BUY --qty N --type MARKET`); preview must
   return `"status": "ACCEPTED"` — any warning -> skip that order, log, alert.
8. FILL TRUTH: confirm each fill via `schwab.py orders --status FILLED` before relying
   on freed cash.
9. DRIFT BAND: skip a leg already within 5% of NAV of target (whole-share granularity
   on ~$1k makes finer targeting meaningless churn).

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
