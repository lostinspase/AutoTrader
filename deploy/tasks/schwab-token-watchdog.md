---
name: schwab-token-watchdog
description: Daily Schwab OAuth token check, 7:00 AM — alerts when the 7-day refresh token is within ~2 days of expiry so trading never silently stops.
---

Daily Schwab token watchdog for the Genesis+Exodus Schwab trading system. Single job: check OAuth token freshness and alert BEFORE the 7-day refresh token expires. No trading, no account reads, no other actions.

PROCEDURE:
1. Run: python3 ~/.claude/skills/genesis-exodus-schwab/scripts/schwab.py token-status
2. Interpret the JSON:
   - If reauth_required=true or authenticated=false: output a LOUD alert — "🔴 SCHWAB TOKEN EXPIRED — the trading system CANNOT read the account or trade until you re-authenticate. Re-auth requires the LONG-WINDOW LISTENER flow — ask Claude to start it. On Linux `schwab.py reauth` does NOT open a browser (it prints the URL), its built-in window is only 5 minutes, and pasting the redirect URL back into chat CANNOT work (Schwab codes expire in ~30s). Keep `ssh -L 8182:127.0.0.1:8182 jploude@100.69.244.45` open, then log in and click through the cert warning to 'Authentication captured'."
   - Else if refresh_days_remaining < 2.5: output "🟡 SCHWAB RE-AUTH DUE SOON — <X> days left (deadline <reauth_by>). Ask Claude to start the long-window re-auth listener (see the expired-case note above). If it lapses, Genesis safe-fails (no trades, no monitoring) and Babel's daily breaker goes degraded until you re-auth."
   - Else: output one line only: "Schwab token OK — <X> days until re-auth (<reauth_by>)."
3. Nothing else. Never print tokens, keys, or secrets.