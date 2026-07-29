# Output Format — SCAN REPORT + BEGINNER SUMMARY

Every FULL scan ends with both blocks below. Fast-path / risk-only runs output just the short summary
plus position/stop status. The lightweight quick-check task uses its own ~4-line format (see its SKILL).

---

## FULL SCAN REPORT (template)

```
══════════════════════════════════════════════
GENESIS + EXODUS — SCAN REPORT
scan_id: <YYYY-MM-DD-HHMM-ET>   mode: LIVE/full-auto
══════════════════════════════════════════════

ACCOUNT
  account: <…agentic_allowed=true…>   access: OK
  portfolio_value: $<nav>
  buying_power (confirmed spendable): $<bp>
  NAV baseline (today): $<baseline>   drawdown: <±x.x%>

PREFLIGHT  (python3 ops.py preflight)
  new_buys_allowed: <true|false>
  block_reasons: [<…>]
  daily_loss_halt: <…>  consecutive_loss_halt: <…>  buys_today: <n>/3  kill_switch: <…>

REGIME (fmp.py regime)
  SPY <px vs 50/200>  QQQ <…>  IWM <…>  VIX <…>
  computed_class: <normal|cautious|defensive|crash>

POSITIONS (broker = source of truth)
  <SYM>  qty <n> (<whole|fractional>)  avg <$>  last <$>  P/L <±%>
         state: <OPEN|TARGET_NEAR|…|FREE_RIDE>  stop: <resting $ / monitored $>  next target: +10% @ <$>
         earnings: <date / none within 5d>   rotation: <ok | rotation_candidate>
  … (one block per holding)

ORDERS (reconciled vs get_equity_orders)
  <resting/open orders, fills since last scan>

ACTIONS TAKEN THIS SCAN
  - <e.g. SOLD 2 SYM @ $x (first target, de-risk 40%); ratcheted stop to $y>
  - <e.g. NO buy — preflight blocked / no qualifying name / priced out of $100 cap>

BUY DISCOVERY  (only if confirmed cash AND in-window AND new_buys_allowed)
  universe scanned: <n names>  engines: Genesis/Exodus/Turtle
  top candidates (score):
    <SYM>  score <x/10>  R:R <x:1>  entry <$>  stop <$>  risk <$ / %>  why: <one line>
  DECISION: <BUY SYM … | NO TRADE | WATCHLIST: …>

RISK NOTES
  <any fragility/sanity flags, data errors, gated names>
══════════════════════════════════════════════
```

---

## BEGINNER SUMMARY (plain English, explain-to-a-13-year-old)

3–6 short sentences. Always include:
- What the market looks like today (calm / shaky / falling).
- What we own and whether anything is near a sell point or a safety stop.
- What we did this scan (sold a piece to lock in gains / nothing / placed a small buy).
- Why we did NOT buy if we didn't (no good setup / out of cash / a safety rule said wait).
- One line on safety state (e.g. "All safety switches normal" or "Buying is paused because …").

Example:
> The market is calm today — the big indexes are above their averages. We own 2 small positions;
> neither is at a sell point or near its safety stop, so we just watched them. We did not buy anything
> because nothing passed all our strict checks and most strong stocks cost more than our $100 limit
> allows for 2 whole shares. All safety switches are normal.
