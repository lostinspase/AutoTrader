# Genesis + Exodus (Schwab edition) — Setup & Status

> Schwab variant of the trading scanner. Reuses the proven safety core (`ops.py`) and FMP data layer
> (`fmp.py`) unchanged; only the broker layer (`schwab.py`, Schwab Trader API OAuth2) is new.

---

## ✅ CURRENT STATE: CONNECTED + HALTED (verified 2026-07-05)

- Schwab app approved (Production, "Ready For Use"), OAuth2 authenticated.
- Account **#41343393 (CASH)** whitelisted; ~$300 cash. Live quotes + orders reachable.
- FMP data layer: 9/9 selftest.
- Two Schwab scheduled tasks registered + enabled (Robinhood tasks disabled).
- **Kill-switch HALTED** — no order can transmit until you run `ops.py resume`.

Re-auth deadline (7-day refresh): check with `schwab.py token-status`.

### Sizing policy (POLICY C — adopted 2026-07-05 after backtest sweep)
Per-name cap changed from "lesser of $100 and 10% of equity" to **"lesser of $100 and 33% of
equity"**, min 2 whole shares kept. Rationale: `scripts/backtest.py --account-grid` over ~5yr
FMP history showed the 10% cap made a $300 account nearly untradable ($30/name -> only sub-$15
stocks). Policy C sim: 30.4% CAGR / -17% maxDD vs 8.4% / -11% for old rules; 1-share entries
tested WORSE (win rate collapsed). Sim is survivorship-biased (today's screener universe) —
treat as upper bound. Rerun: `python3 scripts/backtest.py --account-grid`.

### Gauntlet robustness battery (PASSED 2026-07-05 @ $600, policy C)
`scripts/gauntlet.py --equity 600` — walk-forward: live profile (10/10/25) profitable in 3/3
unseen test folds (and beat fold-tuned params in the weak fold — tuning overfits, fixed profile
holds). Monte Carlo (5000 paths, 29 trades): median $600→$1,464 (19.6% CAGR), 5th-pct still +8%,
P(ending below $600)=0.1%. Jitter: 27/27 parameter neighbors profitable (CV 0.11), all equity
scales $300–$900 profitable. Same survivorship-bias caveat as backtest.py; sample is a mostly-bull
tape. Rerun after any rule change.

### Insider-signal study (2026-07-05): NOT adopted for entry scoring
`scripts/sec.py` (3spread API, key in state/sec.env) provides insider cluster-buy + 13D activist
sensors. Backtest overlay study (35/120 universe names had clusters since 2021, 95 cluster dates):
- 'boost' mode (ranking nudge): ZERO effect — identical results in both sizing modes.
- 'require' mode (gate): destroyed the strategy (1–15 trades, ~0% CAGR) — insider clusters are a
  contrarian/dip signal and rarely coincide with momentum entries.
CONCLUSION: insider signals do NOT enter Genesis entry scoring. sec.py remains available as a
standalone advisory tool (e.g. checking an Exodus rebound candidate for a fresh 13D catalyst, or
heavy insider selling in a holding), but is NOT part of the automated scan procedure.
Rerun the study: sec.py export-signals --start 2021-01-01 <universe>, then
backtest.py --insider-signals state/insider_signals.json --insider-mode boost|require.

### REWARD TEST rule fix (2026-07-08 — first live scan deadlock)
The inherited "R:R >= 2:1 measured at the first target" gate was IMPOSSIBLE by construction with
the 10%-stop/+10%-target profile (always exactly 1:1) — the first live scheduled scan correctly
scored CZR 8/10 and then refused it on this gate, and would have refused everything forever.
Replaced in SKILL.md §7 with the REWARD TEST: profile-conform entries pass by default (the payoff
is the uncapped runner — backtest/MC realized avg win/loss ~2.3:1); reject on reward grounds only
for structurally capped upside or no sane stop. The backtest/gauntlet validated the profile with
no first-target R:R gate, so this change restores the validated design rather than loosening it.

### Crypto study (2026-07-09): Genesis does NOT transfer — plans on ice with evidence
`scripts/crypto_study.py` tested Genesis-on-crypto over BTC/ETH 2022-2026 (window includes the
2022 crash). RESULT: the trend template + any stop variant (fixed 10%, 2.5x ATR, wide trails)
LOSES money on both assets (-1.6% to -11% CAGR, 11-17% win rates) while buy-and-hold made 3.0x on
BTC. Diagnosis: crypto's routine 30-40% shakeouts whipsaw ANY stop-anchored trend entry; the
template's late-stage entry conditions compound it. A crude 200-DMA in/out rule with NO stops
(variant D) DOES work (BTC 3.0x/-31%DD, ETH 2.2x/-38%DD — beats buy-and-hold risk-adjusted) —
but "no stops, ride -30% swings" is a fundamentally different risk contract than this system's
stop-anchored DNA. VERDICT: (a) Genesis/Exodus crypto extension: DEAD, by evidence; (b) if crypto
exposure is ever wanted, it would be a separate small sleeve (spot ETF like IBIT, 200-DMA regime
rule, no intermediate stops, fixed small size) — a deliberate future decision gated on a live
equities track record and explicit user opt-in + walk-forward validation of the D rule;
(c) native 24/7 spot crypto (CCXT): not planned. Rerun: python3 scripts/crypto_study.py

### Broker bugs fixed during connection (all resolved)
1. GET/DELETE requests must NOT carry a `Content-Type` header with no body (Schwab 400s otherwise).
2. Single-symbol quote uses `/quotes?symbols=SYM`, not the `/{sym}/quotes` path form.
3. `orders` requires a `fromEnteredTime`/`toEnteredTime` window (now sends last 7 days).
4. Transient 500-wrapped-in-400 responses are retried (reads only) — but `place-order` NEVER
   auto-retries, so a flaky response cannot double-submit a trade.

---

## STEP 1 — Register the Schwab developer app (a few days for approval)

1. Go to **developer.schwab.com**, create an account, and create a new app.
2. Choose the **Trader API – Individual** product (this is the one that places real orders).
3. Set the app's **Callback URL** to exactly: `https://127.0.0.1:8182`
   (must match `SCHWAB_CALLBACK_URL` in `state/schwab.env`). Schwab requires HTTPS; a localhost
   callback is fine — the browser will show a security/connection warning at the redirect, which is
   expected. You just copy the address-bar URL.
4. Wait for the app status to become **Ready For Use / Approved**. You'll get an **App Key**
   (client_id) and **App Secret** (client_secret).

## STEP 2 — Fill in credentials

Edit `state/schwab.env` (gitignored, chmod 600) and replace the placeholders:
```
SCHWAB_APP_KEY=<your app key>
SCHWAB_APP_SECRET=<your app secret>
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TRADING_ACCOUNT=<the ONE account number allowed to trade>
```
`SCHWAB_TRADING_ACCOUNT` is the safety whitelist: the system reads/trades ONLY this account and
refuses (ACCOUNT_ACCESS_ERROR) if it can't match it among your linked accounts.

## STEP 3 — Authenticate (the OAuth2 flow)

```
python3 scripts/schwab.py auth-url
```
- Open the printed `login_url` in a browser, log into Schwab, approve the app.
- The browser redirects to `https://127.0.0.1:8182/?code=...` (it may show a "can't connect" page —
  that's fine; copy the FULL address-bar URL, including the long `?code=...`).
- Finish:
```
python3 scripts/schwab.py auth-finish "<the full redirect URL you copied>"
```
- Confirm:
```
python3 scripts/schwab.py token-status      # authenticated: true, ~7 refresh_days_remaining
python3 scripts/schwab.py accounts          # should return YOUR whitelisted account
```

## STEP 4 — Verify the data layer

```
python3 scripts/selftest.py                 # want: 9 passed, 0 failed
```

## STEP 5 — Dry run, then arm

1. Do a manual scan (invoke the skill or "Run now" the scheduled task) while HALTED — it should read
   the account, classify regime, and report NO TRADE.
2. When satisfied, arm:
```
python3 scripts/ops.py resume
```

---

## ⚠️ THE 7-DAY RE-AUTH CYCLE (important for autonomy)

Schwab's **refresh token expires hard at 7 days** — a Schwab policy with NO programmatic renewal;
a browser login is required weekly. Access tokens (30 min) refresh automatically in between.

The fast path (~30 seconds, once a week):
```
python3 scripts/schwab.py reauth
```
Opens the Schwab login in your browser and runs a local HTTPS listener on 127.0.0.1:8182 that
captures the redirect automatically — no URL copying. Your browser will warn once about the
localhost self-signed certificate: click Advanced -> Proceed (the redirect never leaves your
machine). When the page says "Authentication captured", you're done.

Fallback (manual): `schwab.py auth-url` -> log in -> copy the redirect URL ->
`schwab.py auth-finish "<url>"`.

Check any time: `python3 scripts/schwab.py token-status`.
A daily scheduled task (`schwab-token-watchdog`, 7 AM) alerts when <2.5 days remain.
When the token is stale, the scanner does NOTHING and reports "SCHWAB RE-AUTH NEEDED" — it never
trades blind.

---

## TIMEZONE (updated 2026-07-16)

The user and machine are now PERMANENTLY on EASTERN time (America/New_York). Crons evaluate in
machine-local time, so they are written directly in ET: full scan `45 9-15 * * 1-5`
(9:45a–3:45p ET), quick-check `0,15,30 9-15 * * 1-5`, watchdog `0 7 * * *`, scorecard Mon 5:30a.
The dashboard refresher and journal parsing are Eastern-anchored via ZoneInfo, so a future machine
TZ change only requires re-deriving the cron hours (market logic is ET-explicit everywhere else).

## LIVE DASHBOARD

**http://127.0.0.1:8090** — served by `scripts/dashboard_server.py`, kept alive by the LaunchAgent
`~/Library/LaunchAgents/com.genesis.dashboard.plist` (auto-starts at login, restarts on crash;
logs at /tmp/genesis_dashboard.log). Pulls FRESH broker data on every page refresh (20s server
cache, 45s page auto-refresh) and shows "updated Ns ago" plus a red banner if the broker or the
server is unreachable. Manage: `launchctl unload|load ~/Library/LaunchAgents/com.genesis.dashboard.plist`.
The older static `state/dashboard.html` (regenerated by the quick-check task) remains as a fallback.

## KILL SWITCH (same as the Robinhood build)
```
python3 scripts/ops.py halt "reason"     # pause (durable)
python3 scripts/ops.py resume            # re-arm
python3 scripts/ops.py live off|on       # disarm/arm live trading
python3 scripts/ops.py ack-losses "note" # USER-ONLY: clear consecutive-loss breaker
```

---

## OUTSTANDING TODO
- [ ] Register + get approval for the Schwab Trader API app.
- [ ] Fill `state/schwab.env` (app key/secret/callback/account).
- [ ] Authenticate; confirm `token-status` and `accounts`.
- [ ] **Rotate the FMP API key** — it was shared in plaintext during the original build.
- [ ] Create the two Schwab scheduled tasks (ask Claude) once auth works.
- [ ] Dry-run a scan, then `ops.py resume`.

Not financial advice. Autonomous live trading carries real financial risk.
