#!/usr/bin/env python3
"""
Genesis-on-crypto study (PHASE 1 — research only, touches nothing live).

Question: does the Genesis trend template + our exit profile produce a survivable,
worthwhile result on BTC/ETH — specifically, does it SIDESTEP the 2022-style crash
(BTC -77%) that buy-and-hold eats?

Adaptations for crypto (calendar-day bars, 365/yr):
  - 52-week window = 365 bars (not 252); CAGR annualized on 365 bars/yr
  - SMAs stay 50/150/200 calendar days (the crypto-conventional trend lines)
  - Exodus deliberately NOT tested: no quality anchor exists in crypto (see SETUP.md)

Variants per asset (single-sleeve sim: in or out, one position):
  A "equity profile":  fixed 10% stop; after +10%, trail 25% off highest close
  B "ATR-scaled":      stop 2.5x ATR20 at entry; after +10%, trail 25%
  C "ATR + wide trail": stop 2.5x ATR20; trail 30%
Entry: template passes at close -> enter next open. Exits at stop/trail (gap-aware).
Benchmark: buy & hold over the same window.

Usage: python3 crypto_study.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fmp  # noqa: E402

ASSETS = ["BTCUSD", "ETHUSD"]
BARS = 2100
YEAR = 365.0


def history(sym):
    d = fmp._get("historical-price-eod/full", {"symbol": sym, "limit": BARS},
                 cache_key=f"cs:{sym}:{BARS}")
    rows = d if isinstance(d, list) else []
    rows = sorted(rows, key=lambda r: r.get("date", ""))
    return [{"date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])} for r in rows]


def precompute(bars):
    closes = [b["close"] for b in bars]
    cum = [0.0]
    for c in closes:
        cum.append(cum[-1] + c)

    def sma(i, w):
        return (cum[i + 1] - cum[i + 1 - w]) / w if i + 1 >= w else None

    trs = [0.0]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    sig = [None] * len(bars)
    for i in range(len(bars)):
        if i + 1 < 365:
            continue
        s50, s150, s200 = sma(i, 50), sma(i, 150), sma(i, 200)
        s200p = sma(i - 30, 200) if i - 30 + 1 >= 200 else None
        if not (s50 and s150 and s200 and s200p):
            continue
        c = closes[i]
        lo52 = min(b["low"] for b in bars[i - 364:i + 1])
        hi52 = max(b["high"] for b in bars[i - 364:i + 1])
        atr20 = sum(trs[max(1, i - 19):i + 1]) / min(20, i)
        sig[i] = {
            "tt": (c > s50 > s150 > s200 and s200 > s200p
                   and c >= lo52 * 1.30 and c >= hi52 * 0.75),
            "atr": atr20,
        }
    return sig


def run(bars, sig, stop_mode, trail_pct):
    eq, in_pos = 1.0, False
    entry = stop = hi_close = 0.0
    runner = False
    trades, wins = 0, 0
    curve = []
    for i in range(1, len(bars)):
        b = bars[i]
        if in_pos:
            # gap-aware stop first
            if b["low"] <= stop:
                fill = min(b["open"], stop)
                eq *= fill / entry
                trades += 1
                wins += 1 if fill > entry else 0
                in_pos = False
            else:
                if not runner and b["high"] >= entry * 1.10:
                    runner = True
                hi_close = max(hi_close, b["close"])
                if runner:
                    stop = max(stop, hi_close * (1 - trail_pct))
        if not in_pos:
            s = sig[i - 1]
            if s and s["tt"]:
                entry = b["open"]
                stop = (entry * 0.90 if stop_mode == "fixed10"
                        else entry - 2.5 * s["atr"])
                hi_close = entry
                runner = False
                in_pos = True
        curve.append(eq * (b["close"] / entry if in_pos else 1.0))
    # mark final
    final = curve[-1]
    peak, maxdd = -1e9, 0.0
    for v in curve:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    years = len(curve) / YEAR
    return {"total_x": round(final, 2),
            "cagr_pct": round((final ** (1 / years) - 1) * 100, 1),
            "maxdd_pct": round(maxdd * 100, 1),
            "trades": trades,
            "win_rate_pct": round(100 * wins / trades, 0) if trades else None}


def main():
    out = {}
    for sym in ASSETS:
        bars = history(sym)
        if len(bars) < 500:
            out[sym] = {"error": f"only {len(bars)} bars"}
            continue
        sig = precompute(bars)
        first = bars[365]["close"]  # benchmark starts where signals become possible
        bh_curve = [b["close"] / first for b in bars[365:]]
        peak, maxdd = -1e9, 0.0
        for v in bh_curve:
            peak = max(peak, v)
            maxdd = min(maxdd, v / peak - 1)
        years = len(bh_curve) / YEAR
        bh = {"total_x": round(bh_curve[-1], 2),
              "cagr_pct": round((bh_curve[-1] ** (1 / years) - 1) * 100, 1),
              "maxdd_pct": round(maxdd * 100, 1)}
        # align sim to same start (signals None before 365 anyway)
        b2, s2 = bars[365:], sig[365:]
        out[sym] = {
            "window": f"{b2[0]['date']}..{b2[-1]['date']}",
            "buy_hold": bh,
            "A_equity_profile_fixed10_trail25": run(b2, s2, "fixed10", 0.25),
            "B_atr2.5_trail25": run(b2, s2, "atr", 0.25),
            "C_atr2.5_trail30": run(b2, s2, "atr", 0.30),
        }
    print(json.dumps(out, indent=1))
    with open(os.path.join(os.path.dirname(HERE), "state", "crypto_study.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
