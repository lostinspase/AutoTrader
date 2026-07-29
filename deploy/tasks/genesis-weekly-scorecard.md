---
name: genesis-weekly-scorecard
description: Weekly Genesis+Exodus scorecard — Mondays 5:30 AM PT (pre-market). Performance measured, not vibed: per-setup stats, gate audit, scheduler reliability.
---

Weekly performance review of the Genesis+Exodus Schwab trading system. READ-ONLY — no trading, no orders, no state changes.

1. Run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/scorecard.py --days 7
   Then also: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/scorecard.py   (all-time)
2. Present both reports concisely, then add a short plain-English assessment covering:
   - Are any engines (genesis/exodus/turtle) showing negative expectancy after >=10 closed trades? (If so, flag for review — do NOT change any rules yourself.)
   - GATE AUDIT: is the average return-since-refusal strongly positive across >=10 samples? That suggests gates are too tight — flag it with the specific refused names.
   - OPS: scheduler reliability — if below 80%, flag loudly with which days were bad.
   - Consecutive-loss or drawdown patterns worth the user's attention.
3. Check token health: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py token-status — remind of the reauth deadline.
4. NEVER change playbook rules, sizing, or gates based on this review — the scorecard informs the human; rule changes happen deliberately with backtest evidence (see SETUP.md history for the process).

Keep the whole output under ~30 lines. This is a mirror, not a steering wheel.