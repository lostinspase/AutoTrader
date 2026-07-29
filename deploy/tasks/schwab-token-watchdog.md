---
name: schwab-token-watchdog
description: Daily Schwab OAuth token check, 7:00 AM — alerts when the 7-day refresh token is within ~2 days of expiry so trading never silently stops.
---

Daily Schwab token watchdog for the Genesis+Exodus Schwab trading system. Single job: check OAuth token freshness and alert BEFORE the 7-day refresh token expires. No trading, no account reads, no other actions.

PROCEDURE:
1. Run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py token-status
2. Interpret the JSON:
   - If reauth_required=true or authenticated=false: output a LOUD alert — "🔴 SCHWAB TOKEN EXPIRED — the trading system CANNOT read the account or trade until you re-authenticate. Run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py reauth   (opens browser; log in, click through the localhost certificate warning, done in ~30 seconds)."
   - Else if refresh_days_remaining < 2.5: output "🟡 SCHWAB RE-AUTH DUE SOON — <X> days left (deadline <reauth_by>). Run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py reauth — takes ~30 seconds. If it lapses, the scanner safe-fails (no trades, no monitoring) until you re-auth."
   - Else: output one line only: "Schwab token OK — <X> days until re-auth (<reauth_by>)."
3. Nothing else. Never print tokens, keys, or secrets.