---
name: genesis-schwab-quick-check
description: Lightweight Genesis SCHWAB position watcher — :00/:15/:30 past the hour, 9:30a–3:30p ET (machine local = Eastern), Mon–Fri. Sells only, never buys.
---

LIGHTWEIGHT POSITION WATCHER for the whitelisted Charles Schwab account (#41343393) — Project Genesis + Exodus, Schwab edition. NOT a full scan. Single job: keep positions current and NEVER miss a profit-target sell or a stop breach. NO buy discovery, NO screener/movers/indicators, NO regime deep-dive, NO long report. Speed and safety only. Fires at :00/:15/:30 past the hour, 9:30a–3:30p EASTERN, Mon–Fri.

MODE — LIVE / full-auto. You MAY place protective SELL orders autonomously (profit partials + stop exits). NEVER place a BUY in this task.

HUMAN-ONLY COMMANDS — ABSOLUTE RULE: NEVER run `ops.py ack-losses` or `ops.py resume` (they clear safety halts and belong to the human alone; deny-blocked at the harness level). A halted/blocked state is honored and reported, never "fixed."

BROKER: `python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py`. Never print secrets/tokens.

FIRST GATES:
- `schwab.py token-status`: if reauth_required/not authenticated -> "SCHWAB RE-AUTH NEEDED — run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py reauth" and stop.
- `schwab.py accounts`: missing/unreadable -> "ACCOUNT ACCESS ERROR — no action" and stop.

TRADING HOURS (ET): market closed/holiday/weekend/pre-open (before 9:30 AM ET) -> "monitor only" and stop. Sells only 9:30 AM–4:00 PM ET.

KILL-SWITCH: `python3 ~/.claude/skills/genesis-exodus-schwab/scripts/ops.py status`. If halt=true, place RISK-REDUCING stop exits ONLY and skip profit-taking; report and stop.

PROCEDURE (fast):
1. schwab.py positions + schwab.py orders (resting/open).
2. schwab.py quotes for EVERY held symbol.
3. FILL TRUTH — reconcile each resting order vs the broker; filled ONLY when status=FILLED or filledQuantity>0. LEDGER: if a position fully closed, FIRST check `tail -5 /Users/jp/.claude/skills/genesis-exodus-schwab/state/ledger.jsonl` — if this close is already recorded, do NOT add again; otherwise ops.py ledger-add ONCE with full detail INCLUDING the "setup" field (genesis|exodus|turtle — look it up in the journal entry that bought it). Respect a skipped_duplicate response — never work around it.
4. Per position compute % vs averagePrice. First profit target = +10%.
5. PROFIT TARGETS: if price >= +10% and no take-profit sell exists, sell ~40% (floor(0.40*shares), whole shares) via schwab.py preview-order then place-order (marketable LIMIT at/just below bid); then ratchet the resting STOP UP toward ~10% below current (cancel-order + place new STOP, never lower).
6. STOPS: verify the resting GTC STOP is still WORKING; if missing, re-place. Ratchet up, never down. If price <= stop and no stop is resting, place a protective marketable-LIMIT exit.
7. ANY SELL: schwab.py preview-order first; place only if clean and within ET regular hours; never duplicate; if price moved >3% vs the quote you saw, re-check first. Never auto-retry a placement.
8. NO new buys. NO discovery. NO regime analysis.
9. JOURNAL — append exactly ONE compact JSON line to /Users/jp/.claude/skills/genesis-exodus-schwab/state/journal.jsonl (ABSOLUTE path) with "ts" = ISO-8601 WITH local offset (`date '+%Y-%m-%dT%H:%M:%S%z'`), run_type "quick_check", liquidationValue, cashAvailableForTrading, per-position list, fills, orders, decision.
10. LAST STEP always: regenerate the dashboard — `python3 ~/.claude/skills/genesis-exodus-schwab/scripts/report.py` (no --open).

OUTPUT (max ~4 lines): one line per position — symbol, % vs entry, status. If a sell happened, ONE plain-language sentence. If nothing actionable: "All N positions ok." If no positions: "No positions held."

Read only ~/.claude/skills/genesis-exodus-schwab/SKILL.md §5/§6/§8 + references/execution.md. Skip §7 (discovery) and §10 (full report).