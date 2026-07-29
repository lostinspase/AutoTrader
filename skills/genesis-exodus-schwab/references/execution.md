# Execution — Schwab Trader API order mechanics

All orders go through `scripts/schwab.py` (Schwab Trader API, OAuth2). ALWAYS `schwab.py preview-order`
before `place-order`. The broker is the source of truth; reconcile every resting order against
`schwab.py orders` each scan. Never infer a fill (see FILL TRUTH in SKILL.md §0).

Build order JSON with `schwab.py build-order` (canonical schema) rather than hand-writing it.

---

## WHOLE-SHARES ONLY

Schwab's Trader API does not place fractional equity orders here, so every entry is whole-share.
New entries are >=2 shares so a protective GTC stop can rest. With the $100 cap, names above
~$50/share can't fit 2 shares -> WATCHLIST or pick a cheaper qualifying name.

---

## ORDER SCHEMA (verified)

Simple equity LIMIT buy:
```json
{
  "session": "NORMAL",
  "duration": "DAY",
  "orderType": "LIMIT",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {"instruction": "BUY", "quantity": 8, "instrument": {"symbol": "F", "assetType": "EQUITY"}}
  ],
  "price": "12.55"
}
```

Protective STOP (rests GTC):
```json
{
  "session": "NORMAL",
  "duration": "GOOD_TILL_CANCEL",
  "orderType": "STOP",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {"instruction": "SELL", "quantity": 8, "instrument": {"symbol": "F", "assetType": "EQUITY"}}
  ],
  "stopPrice": "11.30"
}
```

`instruction`: BUY / SELL only (NEVER SELL_SHORT — long-only). `orderType`: MARKET / LIMIT / STOP.

---

## NEW BUY (entry)

1. Confirm token valid (`schwab.py token-status`), `new_buys_allowed=true` (preflight), in-window
   (9:45a–3:45p ET), confirmed cash.
2. Size: shares = min(by-risk, by-dollar-cap), whole number >=2 (playbooks.md sizing math).
3. Define stop (~10% below entry) BEFORE entry.
4. Build a **marketable LIMIT** at/just above the ask:
   `schwab.py build-order --symbol SYM --side BUY --qty N --type LIMIT --price <ask>`
5. `schwab.py preview-order '<json>'` -> if it warns/errors, DO NOT place; log + alert.
6. If price moved >3% vs the signal, re-check first (data/fragility halt).
7. `schwab.py place-order '<json>'`. A successful placement returns a Location header / order id.
8. Immediately rest the protective GTC STOP:
   `schwab.py build-order --symbol SYM --side SELL --qty N --type STOP --stop <stopPx>` -> preview -> place.
9. Record: `ops.py buy-record '{"symbol":"SYM","shares":N,"entry":px,"stop":sx}'`.

---

## TAKE-PROFIT (first target +10%, de-risk 40%)

On a scan, if last >= entry*1.10 and no take-profit sell exists:
1. Sell `floor(0.40 * shares)` whole shares via a reviewed marketable LIMIT at/just below the bid.
2. Ratchet the resting STOP UP toward ~10% below current: cancel the old stop
   (`schwab.py cancel-order <id>`), then place a new STOP at the higher level. NEVER lower a stop.
3. Do NOT move to breakeven — runner rides with a ~25% trailing stop off the highest close, no cap.

Never reuse freed capital until the sell shows FILLED AND `schwab.py positions` cash has risen.

---

## STOP EXIT

The Schwab GTC STOP fires on its own. Each scan, verify it's still WORKING; if missing, re-place.
Ratchet up only, never widen. On a fully-closed position append
`ops.py ledger-add '{"symbol":"SYM","outcome":"stop|win|loss","realized_pl":x,"realized_pct":y,"setup":"genesis|exodus|turtle"}'`.

---

## CANCEL / REPLACE

Schwab has no atomic replace here — cancel then place. Confirm the cancel shows CANCELED (reconcile
via `schwab.py orders`) before placing the replacement, so you never double-rest a stop.

---

## TOKEN REFRESH DURING A RUN

`schwab.py` auto-refreshes the 30-min access token when stale. If the 7-day refresh token has
expired, every command exits ACCOUNT_ACCESS_ERROR — the scan does nothing and must alert the user to
re-auth (`schwab.py auth-url` -> `auth-finish`). Check ahead with `schwab.py token-status`.
