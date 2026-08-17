---
name: ark2-weekly-check
description: Project ARK2 weekly trend check — Fridays 10:15 ET. Exits any holding >3% below its 10-mo SMA to cash. Sells only, never buys (except SGOV with proceeds).
---

PROJECT ARK2 weekly trend check (Schwab account **95762912** ONLY — never …3393 Genesis, never …5301 Babel). **SELLS ONLY** — never buy anything except SGOV with confirmed proceeds. This is NOT a rebalance; it is the mid-month exit valve.

GATES (stop and report if any fail):
- Market open, regular hours.
- Kill switch: `python3 ~/.claude/skills/project-ark2/scripts/ops.py status` — halted=true -> report only.
- Schwab token: any ACCOUNT_ACCESS_ERROR -> STOP, no orders, report (re-auth is human-only).

1. `python3 ~/.claude/skills/project-ark2/scripts/ark2.py weekly-check` — deterministic: flags any current-target holding trading >3% below its 10-month SMA. If "all_clear" is true -> NO ORDERS, journal, stop (this is the normal outcome most weeks).
2. If it returns "error" or a per-symbol data error -> no action on that symbol, journal, report. Never improvise an exit the engine did not call for.
3. For each FLAGGED holding: confirm it is ACTUALLY HELD via `schwab.py positions` with the exact share count (never sell a quantity the engine inferred but the broker does not report). Then SELL the FULL position, whole shares:
   ```
   ORDER=$(python3 ~/.claude/skills/project-ark2/scripts/schwab.py build-order \
       --symbol SOXQ --side SELL --qty <ALL held shares> --type MARKET)
   python3 ~/.claude/skills/project-ark2/scripts/schwab.py preview-order "$ORDER"
   python3 ~/.claude/skills/project-ark2/scripts/schwab.py place-order "$ORDER"
   ```
   Preview must return `"status": "ACCEPTED"`; any warning -> skip, log, alert. Confirm the fill via `schwab.py orders --status FILLED` (FILL TRUTH).
4. Proceeds: this is a CASH account, so sell proceeds settle T+1 and are NOT spendable today. Do NOT buy SGOV with unsettled proceeds — leave them as cash and note it in the journal. The next monthly rebalance will place them.
5. JOURNAL (always, even all-clear): append ONE JSON line to `~/.claude/skills/project-ark2/state/journal.jsonl` with "ts" (ISO-8601 WITH local offset), "run_type": "weekly_check", "flags", "orders", "fills", "decision", "nav" (liquidationValue as a NUMBER), "cash", AND "positions": ALL current holdings as {"symbol","shares","avg","price"} — the strategy monitor reads this field.
6. OUTPUT: max 5 lines.

Never touch any other account. Never buy a thematic ETF in this job — only the monthly rebalance may add exposure. Never loop-retry a blocked order. NEVER run ops.py ack-losses or resume (human-only).
