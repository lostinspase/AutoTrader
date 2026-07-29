# Genesis / Exodus / Turtle — Entry Playbooks, Trend Template, Scoring, Universe

All technical levels are COMPUTED by `scripts/fmp.py` — never invent one. If FMP errors for a
candidate, that name is WATCHLIST/NO TRADE, never a guessed buy.

---

## THE TREND TEMPLATE (Genesis quality gate)

A name must pass the full template (computed in `fmp.py indicators` as
`genesis_trend_template_pass`) to be Genesis-eligible:

1. Price > SMA50 > SMA150 > SMA200 (proper stacking).
2. SMA200 rising (slope positive over ~1 month).
3. >=252 bars of history (a real 52-week window; otherwise the name is gated out — no faking it).
4. Price >= 30% above the 52-week LOW.
5. Price within 25% of the 52-week HIGH (`pct_from_hi >= -25`).

If `fiftytwo_week_complete` is false, the name FAILS the template by construction — never buy it.

---

## ENGINE 1 — GENESIS (own-the-leaders momentum)

Primary discovery engine. Goal: hold the strongest trend-template names ranked by relative strength.

Source: `fmp.py screener` for the liquid quality universe, then `fmp.py indicators SYM` per candidate.

A Genesis BUY candidate:
- Passes the full trend template.
- High blended relative strength (`fmp.py rs SYM` -> `rs_excess_vs_spy > 0`, ideally top of the pack).
- A fresh 20- or 55-day breakout (`breakout20` / `breakout55`) is a PLUS, not a requirement.
- Healthy liquidity (`avgDollarVol20` comfortably above your size).
- Defined stop ~10% below entry (or just under the most recent higher-low if tighter).

## ENGINE 2 — EXODUS (high-quality rebound)

Rebound engine. Source: `fmp.py movers` -> use the **losers** list. A name only qualifies if it is a
quality name having a temporary pullback, NOT a falling knife:
- Still above its rising SMA200 (long-term uptrend intact).
- Pullback into support (e.g. near SMA50) on no broken structure.
- Positive longer-window RS despite the short-term drop.
- Clear invalidation level for the stop (recent swing low).
Reject anything that broke its 200-DMA, has collapsing RS, or is news-impaired.

## ENGINE 3 — TURTLE (breakout system)

Classic Donchian breakout: enter on a new 20- or 55-day high (`breakout20`/`breakout55`), stop at
~2x ATR(20) below entry. **Turtle only fires if the name ALSO passes Genesis quality** (trend
template + RS). No low-quality breakouts.

---

## SCORING (0–10) — score each candidate

Add points; a BUY requires confidence **>=7** AND **R:R >=2:1**.

| Factor                                            | Points |
|---------------------------------------------------|--------|
| Full trend template pass                          | +3     |
| Blended RS positive & high (leader)               | +2     |
| Fresh breakout (20/55d)                           | +1     |
| Regime is NORMAL (vs CAUTIOUS)                     | +1     |
| Clean structure / tight stop available            | +1     |
| Strong liquidity (avgDollarVol20 >> size)         | +1     |
| Supportive sensors (breadth risk-on, no rotation-out, low correlation to book) | +1 |
| Earnings within ~5 trading days                   | **DISQUALIFY -> WATCHLIST** |
| Regime DEFENSIVE/CRASH                             | **cap score; usually NO TRADE** |
| FMP data error / <252 bars                         | **DISQUALIFY** |

R:R = (target distance) / (entry − stop distance). Target for R:R math = +10% first target; runner
upside is uncapped but not counted in the gate.

---

## UNIVERSE (what the screener must return)

`fmp.py screener` returns liquid, quality, **US, non-ETF, non-fund** names: marketCap >= $2B,
price >= $5, volume >= 500k, actively trading. The universe MUST span multiple sectors and BOTH major
exchanges — `selftest.py` asserts that JPM/XOM/LLY (canonical NYSE leaders) appear and that >=4 sectors
are represented. If those vanish, the screener has regressed (e.g. gone NASDAQ-only) and the scan is
NOT to be trusted until fixed.

NOTE on this account's $100 cap: many screener leaders trade well above $50/share and therefore cannot
satisfy whole-shares-only (>=2 shares <= $100). They still belong in discovery for RS/regime context,
but for an actual BUY you must pick a qualifying name priced so 2+ whole shares fit $100, else WATCHLIST.

---

## POSITION SIZING MATH

1. Risk budget = 2% of equity.
2. Per-share risk = entry − stop (~10% of entry).
3. Shares by risk = floor(risk budget / per-share risk).
4. Shares by dollar cap = floor(min($100, 10% equity) / entry).
5. Final shares = min(step 3, step 4), and must be a WHOLE number **>=2**.
6. If final shares < 2 -> the name doesn't fit; pick a cheaper equivalent or skip.
