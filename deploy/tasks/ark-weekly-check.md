---
name: ark-weekly-check
description: Project Ark weekly trend check — Fridays 10:05 ET. Exits any holding >3% below its 10-mo SMA to SGOV. Sells only, never buys.
---

PROJECT ARK weekly trend check (Robinhood account 451480438 ONLY). SELLS ONLY — never buy anything except SGOV with proceeds. NOT a rebalance.

GATES: market open (regular hours); kill switch `python3 ~/.claude/skills/project-ark/scripts/ops.py status` (halt=true -> report only).

1. `python3 ~/.claude/skills/project-ark/scripts/ark.py weekly-check` — deterministic: flags any current-target holding trading >3% below its 10-month SMA.
2. If all_clear: no orders.
3. For each FLAGGED holding: verify actually held (get_equity_positions); sell the FULL position via fractional notional order (review_equity_order first; warning -> skip + alert); confirm fill; buy SGOV with confirmed proceeds (review first). Data error on a symbol -> no action on it, report.
4. JOURNAL (always, even all-clear): ONE JSON line to /Users/jp/.claude/skills/project-ark/state/journal.jsonl with "ts" (ISO-8601 with local offset), run_type "weekly_check", flags, orders, decision, nav (get_portfolio total_value as a NUMBER), cash, AND "positions": ALL current holdings as {"symbol","shares","avg","price"} (from get_equity_positions + quotes) — the strategy monitor reads this field.
5. OUTPUT: max 5 lines.

Never touch any other account. Never loop-retry a blocked order. NEVER run ops.py ack-losses or resume (human-only).