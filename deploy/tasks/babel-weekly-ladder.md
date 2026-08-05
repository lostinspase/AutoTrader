---
name: babel-weekly-ladder
description: Project Babel weekly ladder — Mondays 09:45 ET. The ONLY run that may increase exposure or switch leaders. Schwab account 20425301 only.
---

PROJECT BABEL weekly ladder (Schwab account **20425301** ONLY — never …3393 Genesis, never Robinhood). This is the ONLY run permitted to INCREASE exposure or switch leaders.

GATES (stop and report if any fail):
- Market open, regular hours.
- Kill switch: `python3 ~/.claude/skills/project-babel/scripts/ops.py status` — halted=true -> report only, no orders.
- Schwab token: if any command returns ACCOUNT_ACCESS_ERROR -> STOP, no orders, report (re-auth is human-only).

1. `python3 ~/.claude/skills/project-babel/scripts/babel.py target` — deterministic engine. It prints "governor.tier" (3, 1, or 0), "selector.leader" (QQQ or SPY), and "target_weights". If it returns "error" -> NO TRADE, journal, report. NEVER override the tier, pick a different vehicle, or size above the tier.
2. `python3 ~/.claude/skills/project-babel/scripts/schwab.py positions` — current holdings + balances. Use **cashBalance (settled cash)** for sizing. THIS IS A MARGIN ACCOUNT: ignore buyingPower entirely; never let total invested exceed NAV (liquidationValue). Never short, no options.
3. Compare current holdings to target_weights. If already at the target state (same symbols, each within 5% of NAV of target) -> NO ORDERS, journal "already at target".
4. Otherwise: **SELLS FIRST** (frees cash), then buys. WHOLE shares only — round DOWN, never up. Residual cash is expected (~3% at 3x, ~10% at 1x/cash) and is correct; do not add a share to close the gap.
5. For EVERY order: `schwab.py preview-order` first (build with `schwab.py build-order SYMBOL BUY|SELL QTY MARKET`); any warning -> skip that order, log, alert. Then place, then confirm the fill via `schwab.py orders filled` before relying on freed cash (FILL TRUTH).
6. JOURNAL (always, even no-trade): append ONE JSON line to `~/.claude/skills/project-babel/state/journal.jsonl` with "ts" (ISO-8601 WITH local offset), "run_type": "weekly_ladder", "tier", "leader", "nav" (liquidationValue as a NUMBER), "cash", "target_weights", "orders", "fills", "decision", AND "positions": ALL current holdings as {"symbol","shares","avg","price"} — the strategy monitor reads this field. Also append the decision line to `~/.claude/skills/project-babel/state/babel_history.jsonl`.
7. OUTPUT: max 5 lines — tier, leader, orders placed, fills, ending exposure.

Never touch any other account. Never loop-retry a blocked order. NEVER run ops.py ack-losses or resume (human-only). A ~50% drawdown is within design — do NOT halt the strategy for drawdown alone.
