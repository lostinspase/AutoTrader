---
name: ark-monthly-rebalance
description: Project Ark monthly rebalance — fires 10:00 ET on days 1–4; executes only on the month's first trading day. Robinhood acct 451480438 only.
---

PROJECT ARK monthly rebalance (multi-asset ETF rotation, Robinhood account 451480438 ONLY — never any other account, never Schwab).

GATE 1 — first trading day: this task fires at 10:00 ET on calendar days 1–4. Execute the rebalance ONLY if today is the month's FIRST trading day (weekday, not a US market holiday). Otherwise output "not first trading day — no action" and stop.
GATE 2 — kill switch: `python3 ~/.claude/skills/project-ark/scripts/ops.py status`; halt=true -> report and stop. NEVER run ops.py ack-losses or resume (human-only).
GATE 3 — market open + regular hours (fractional orders are regular-hours only).

READ AND FOLLOW ~/.claude/skills/project-ark/SKILL.md exactly. Summary:
1. `python3 ~/.claude/skills/project-ark/scripts/ark.py targets` — deterministic engine computes target weights (FLOODGATE/TREND/ROTATE). NEVER override or improvise weights. Engine error -> NO REBALANCE, report, stop.
2. Robinhood MCP: get_portfolio + get_equity_positions + get_equity_orders (451480438). SETTLED cash only.
3. Dollar targets = weight × NAV. DRIFT BAND: only trade positions whose current-vs-target weight differs by >2% of NAV; always trade new entries and full exits. SELLS FIRST, then buys. Fractional NOTIONAL (dollar) orders. review_equity_order before EVERY placement; warning -> skip that order, log, alert. Confirm fills (get_equity_orders) before relying on freed cash. NO margin/shorting/options/crypto; never exceed 100% invested. SGOV is BOUGHT like any position.
4. JOURNAL: ONE JSON line to /Users/jp/.claude/skills/project-ark/state/journal.jsonl with "ts" (ISO-8601 with local offset via `date '+%Y-%m-%dT%H:%M:%S%z'`), run_type "rebalance", nav (NUMBER, not string), cash, targets, orders, fills, decision, AND "positions": ALL current post-rebalance holdings as {"symbol","shares","avg","price"} — the strategy monitor reads this field. If a prior month's targets existed, append that month's realized portfolio return to /Users/jp/.claude/skills/project-ark/state/ark_history.json port_rets as {"month":"YYYY-MM","ret":<decimal>}.
5. OUTPUT: signal month, crash_override status, target table, orders + fills, plain-English one-liner.

If the harness blocks an order do NOT loop-retry — log, alert, continue with remaining orders. Patience over churn.