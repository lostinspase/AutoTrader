---
name: babel-daily-breaker
description: Project Babel daily emergency de-lever — market days 09:50 ET. EXIT-ONLY: may sell to SGOV, may NEVER buy leverage or switch leaders. Schwab account 20425301 only.
---

PROJECT BABEL daily breaker (Schwab account **20425301** ONLY). **EXIT-ONLY RUN.** This job may de-lever to cash/SGOV and NOTHING ELSE. It may NEVER increase exposure, NEVER re-lever, NEVER switch leaders — even if conditions look perfect. Only the Monday weekly ladder may add exposure. This run is Babel's tail-risk control; a missed run is the strategy's core operational risk.

GATES (stop and report if any fail):
- Market open, regular hours.
- Kill switch: `python3 ~/.claude/skills/project-babel/scripts/ops.py status` — halted=true -> report only.
- Schwab token: ACCOUNT_ACCESS_ERROR -> STOP, no orders, report (re-auth is human-only).

1. `python3 ~/.claude/skills/project-babel/scripts/babel.py daily-check` — deterministic. It reads the last target to learn the held tier/leader, then tests ONLY that leader for a breach (price < 200-DMA OR 20d vol > 35%). Output has "de_lever": true|false. If it returns "error" -> NO TRADE, journal, report.
2. If `de_lever` is **false** -> NO ORDERS. Journal and stop. (This is the normal outcome most days.)
3. If `de_lever` is **true**: `schwab.py positions`, then SELL the FULL leveraged position (TQQQ or UPRO — whole shares, the entire holding), in this exact form (verified 2026-08-05):
   ```
   ORDER=$(python3 ~/.claude/skills/project-babel/scripts/schwab.py build-order \
       --symbol TQQQ --side SELL --qty <ALL held shares> --type MARKET)
   python3 ~/.claude/skills/project-babel/scripts/schwab.py preview-order "$ORDER"
   python3 ~/.claude/skills/project-babel/scripts/schwab.py place-order "$ORDER"
   ```
   Preview must return `"status": "ACCEPTED"`; any warning -> skip, log, alert. Confirm each fill via `schwab.py orders --status FILLED` (FILL TRUTH).
4. With confirmed proceeds, BUY SGOV with settled cash (whole shares, round DOWN). This is the ONLY buy this job may ever place — SGOV only, never a leveraged ETF. Residual cash is fine.
5. JOURNAL (always, even no-action): append ONE JSON line to `~/.claude/skills/project-babel/state/journal.jsonl` with "ts" (ISO-8601 WITH local offset), "run_type": "daily_check", "de_lever", "checked_leader", "tier", "nav" (liquidationValue as a NUMBER), "cash", "orders", "fills", "decision", AND "positions": ALL current holdings as {"symbol","shares","avg","price"} — the strategy monitor reads this field and uses it as Babel's heartbeat.
6. OUTPUT: max 3 lines.

Never touch any other account. Never loop-retry a blocked order. NEVER run ops.py ack-losses or resume (human-only). A ~50% drawdown is within design — the governor handles risk; do NOT improvise an exit the engine did not call for, and do NOT skip an exit the engine DID call for.
