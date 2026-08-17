---
name: ark2-monthly-rebalance
description: Project ARK2 monthly rebalance — fires 10:10 ET on days 1–4; executes only on the month's first trading day. Schwab acct 95762912 only.
---

PROJECT ARK2 monthly rebalance (Schwab account **95762912** ONLY — never …3393 Genesis, never …5301 Babel, never Robinhood). Thematic sleeve; runs alongside Project Ark, which is a SEPARATE strategy in a different account — do not read or touch Ark's holdings.

FIRST-TRADING-DAY GATE: this task fires on days 1–4. Execute ONLY if today is the month's FIRST TRADING day (check the market calendar / that no earlier weekday this month was a trading day). Otherwise output "not the first trading day — no action" and stop. Do NOT catch up a missed month.

GATES (stop and report if any fail):
- Market open, regular hours (whole-share market orders only).
- Kill switch: `python3 ~/.claude/skills/project-ark2/scripts/ops.py status` — halted=true -> report only, no orders.
- Schwab token: any ACCOUNT_ACCESS_ERROR -> STOP, no orders, report (re-auth is human-only).

1. `python3 ~/.claude/skills/project-ark2/scripts/ark2.py targets` — deterministic engine (universe SOXQ/XLE/TLT/GLDM, top 2 held). Prints target_weights. If it returns "error" -> NO REBALANCE, journal, report. NEVER override, re-score, or improvise weights.
2. `python3 ~/.claude/skills/project-ark2/scripts/schwab.py positions` — current holdings + balances. Use **cashBalance (settled cash)** for sizing; this is a CASH account, so proceeds from today's sells may NOT be spendable until T+1. If a buy needs unsettled proceeds, place what settled cash allows and journal the shortfall — do NOT wait, do NOT borrow.
3. Compute dollar targets = weight × NAV (liquidationValue). DRIFT BAND: skip any leg already within 5% of NAV of its target; always trade new entries and full exits.
4. **WHOLE SHARES ONLY — round DOWN, never up.** Residual cash (~15% at $1k) is expected and is the SAFE error. A SGOV leg that rounds to 0 shares is FINE — leave it as literal cash; do not force a purchase.
5. **SELLS FIRST**, then buys. For EVERY order (verified syntax):
   ```
   ORDER=$(python3 ~/.claude/skills/project-ark2/scripts/schwab.py build-order \
       --symbol SOXQ --side BUY --qty 3 --type MARKET)
   python3 ~/.claude/skills/project-ark2/scripts/schwab.py preview-order "$ORDER"
   python3 ~/.claude/skills/project-ark2/scripts/schwab.py place-order "$ORDER"
   ```
   Preview must return `"status": "ACCEPTED"` and `orderBalance.projectedAvailableFund` >= 0; any warning, rejection, or negative projected funds -> SKIP that order, log, alert.
6. FILL TRUTH: confirm every fill via `schwab.py orders --status FILLED` before relying on freed cash or reporting a position.
7. JOURNAL (always, even no-trade): append ONE JSON line to `~/.claude/skills/project-ark2/state/journal.jsonl` with "ts" (ISO-8601 WITH local offset), "run_type": "rebalance", "nav" (liquidationValue as a NUMBER), "cash", "targets", "orders", "fills", "decision", AND "positions": ALL current holdings as {"symbol","shares","avg","price"} — the strategy monitor reads this field. After a COMPLETED rebalance also append the realized prior-month return to `~/.claude/skills/project-ark2/state/ark2_history.json` (the engine's vol-target input): {"month": "YYYY-MM", "ret": <decimal>}.
8. OUTPUT: max 5 lines — targets, orders placed, fills, ending positions, cash.

Never touch any other account. Never loop-retry a blocked order. NEVER run ops.py ack-losses or resume (human-only). This sleeve is volatile by design (-13.3% backtested maxDD, ~36% losing months) — do NOT halt it for drawdown alone, and do NOT improvise a defensive trade the engine did not call for.
