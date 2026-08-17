#!/usr/bin/env python3
"""
Project ARK2 — thematic sleeve. Same deterministic engine as Ark, different universe.

WHY A SEPARATE SLEEVE INSTEAD OF ADDING SMH/XLE TO ARK: inside one engine the
thematic ETFs merely COMPETE with VOO/VEA for the same 4 slots, displacing the
diversified base rather than adding to it. Run as its own engine, ARK2's returns
are nearly UNCORRELATED with Ark's (0.055, and stable at +0.064/-0.068/+0.130
across three sub-periods), so a 50/50 blend produces:
    Ark(10) alone   CAGR  7.32%  maxDD -12.7%  Sharpe 0.70
    Ark(12) folded  CAGR  9.01%  maxDD -12.9%  Sharpe 0.80
    ARK2 alone      CAGR 11.77%  maxDD -18.7%  Sharpe 0.91
    50/50 blend     CAGR  9.74%  maxDD -10.4%  Sharpe 1.12   <- higher return AND
                                                                shallower drawdown
Gauntlet: backtests/ark2_gauntlet.py, 6/6 (walk-forward 3/3, correlation stability
3/3, jitter 4/4, universe perturbation 6/6, drawdown guard, equal-capital fairness).

THE PERTURBATION RESULT MATTERS MOST: dropping SMH entirely STILL beat Ark(10)
alone. The edge comes from having a second uncorrelated sleeve, not from
semiconductors specifically. Do not treat the exact tickers as sacred.

CAVEATS: constituents were chosen in 2026 knowing semis/energy led this cycle, and
a 4-asset/2-slot universe is inherently more fragile than Ark's 12-asset one.
Expect a smaller live edge. STANDALONE this sleeve is volatile: -18.7% maxDD and
~36% losing months. It will be red while Ark is green -- that is the mechanism
working, not a malfunction.

Engine (identical to ark.py):
  FLOODGATE  crash override (SPY AND TLT < 10-mo SMA -> 100% SGOV); absolute momentum
             vs SGOV; 10% vol target on trailing 6 realized monthly portfolio returns
  TREND      eligible = month-end price > 10-month SMA AND 12-1 momentum > 0
  ROTATE     top 2 by blended 3/6/12-mo momentum, inverse-vol weights, 60% class cap

The engine only COMPUTES targets — it never places orders. The scheduled task
translates targets into Robinhood fractional notional orders.

CLI:
  targets            compute + persist state/ark2_targets.json, print summary
  weekly-check       mid-month exit test: flag holdings >3% below their 10-mo SMA
  history            show recorded monthly portfolio returns (vol-target input)
"""

import datetime as dt
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
sys.path.insert(0, HERE)
import fmp  # noqa: E402

# symbol -> asset class. TLT is REQUIRED (the FLOODGATE crash override reads it)
# and doubles as a defensive destination; GLD gives the trend gate somewhere to go
# that is not equity beta. SMH/XLE are the thematic engine.
# TESTED ALTERNATIVES (all still beat Ark(10) alone in the blend): drop_GLD 0.93,
# drop_XLE 1.08, drop_SMH 0.82, swap SMH->XLK 1.18, add_IEF 1.14. As-designed 1.12.
UNIVERSE = {
    "SMH": "semis",
    "XLE": "energy",
    "TLT": "treasuries",
    "GLD": "gold",
}
CASH = "SGOV"
BENCH = "SPY"
# Concentrated by design: 2 slots from a 4-asset universe. CLASS_CAP is effectively
# inert here (every asset is its own class) but is kept at the tested 0.60 so the
# engine code stays byte-identical to Ark's.
TOP_N = 2
CLASS_CAP = 0.60
VOL_TARGET = 0.10
TARGETS_FILE = os.path.join(STATE, "ark2_targets.json")
HISTORY_FILE = os.path.join(STATE, "ark2_history.json")


def month_end_series(sym):
    """{'YYYY-MM': last close of that month} from FMP daily bars (adjusted)."""
    d = fmp._get("historical-price-eod/full", {"symbol": sym, "limit": 500},
                 cache_key=f"ark2:{sym}")
    rows = d if isinstance(d, list) else []
    rows = sorted(rows, key=lambda r: r.get("date", ""))
    me = {}
    for r in rows:
        me[r["date"][:7]] = float(r.get("adjClose") or r["close"])
    return me, (rows[-1]["date"] if rows else None)


def compute():
    syms = list(UNIVERSE) + [CASH, BENCH]
    me, latest = {}, {}
    for s in syms:
        me[s], latest[s] = month_end_series(s)
        if not me[s]:
            return {"error": f"no data for {s} — NO REBALANCE (data-fragility rule)"}

    # completed months only: drop the current (partial) month
    this_month = dt.date.today().strftime("%Y-%m")
    months = sorted(set.intersection(*(set(me[s]) for s in syms)) - {this_month})
    if len(months) < 14:
        return {"error": f"only {len(months)} common completed months — insufficient lookback"}
    m = months[-1]           # last completed month
    idx = {mm: i for i, mm in enumerate(months)}

    def px(s, mm): return me[s][mm]

    def ret(s, k):  # k-month return ending at m
        i = idx[m]
        return px(s, months[i]) / px(s, months[i - k]) - 1 if i >= k else None

    def sma10(s):
        i = idx[m]
        if i < 9:
            return None
        return st.mean(px(s, months[j]) for j in range(i - 9, i + 1))

    def mom_12_1(s):
        i = idx[m]
        return px(s, months[i - 1]) / px(s, months[i - 12]) - 1 if i >= 12 else None

    def blended(s):
        rs = [ret(s, k) for k in (3, 6, 12)]
        rs = [r for r in rs if r is not None]
        return sum(rs) / len(rs) if len(rs) == 3 else None

    crash = (px(BENCH, m) < (sma10(BENCH) or 1e18)) and (px("TLT", m) < (sma10("TLT") or 1e18))

    signals, weights = {}, {}
    cash_bl = blended(CASH) or 0.0
    for s in UNIVERSE:
        sm = sma10(s)
        signals[s] = {
            "month_end_px": round(px(s, m), 2), "sma10": round(sm, 2) if sm else None,
            "above_sma10": bool(sm and px(s, m) > sm),
            "mom_12_1": round(mom_12_1(s) or 0, 4),
            "blended": round(blended(s) or 0, 4),
            "beats_cash": bool((blended(s) or -1) > cash_bl),
        }
    if not crash:
        elig = [s for s in UNIVERSE
                if signals[s]["above_sma10"] and signals[s]["mom_12_1"] > 0
                and signals[s]["beats_cash"]]
        chosen = sorted(elig, key=lambda s: -signals[s]["blended"])[:TOP_N]
        if chosen:
            i = idx[m]
            vols = {}
            for s in chosen:
                rets = [px(s, months[j]) / px(s, months[j - 1]) - 1
                        for j in range(i - 11, i + 1)]
                vols[s] = max(st.pstdev(rets), 1e-6)
            tot = sum(1 / v for v in vols.values())
            w = {s: (1 / vols[s]) / tot for s in chosen}
            w = {s: v * len(chosen) / TOP_N for s, v in w.items()}  # unfilled -> cash
            by_class = {}
            for s in w:
                by_class.setdefault(UNIVERSE[s], []).append(s)
            for cls, ss in by_class.items():
                t = sum(w[s] for s in ss)
                if t > CLASS_CAP:
                    for s in ss:
                        w[s] *= CLASS_CAP / t
            weights = w

    # vol targeting on trailing 6 realized monthly portfolio returns (recorded live)
    hist = {"port_rets": []}
    try:
        with open(HISTORY_FILE) as f:
            hist = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    vol_scalar = 1.0
    if len(hist.get("port_rets", [])) >= 6:
        vol = st.pstdev([r["ret"] for r in hist["port_rets"][-6:]]) * (12 ** 0.5)
        if vol > VOL_TARGET:
            vol_scalar = VOL_TARGET / vol
            weights = {s: v * vol_scalar for s, v in weights.items()}

    cash_w = round(1.0 - sum(weights.values()), 4)
    out = {
        "as_of": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "signal_month": m,
        "latest_data_date": latest[BENCH],
        "crash_override": crash,
        "vol_scalar": round(vol_scalar, 3),
        "signals": signals,
        "target_weights": {**{s: round(v, 4) for s, v in weights.items()},
                           CASH: cash_w},
        "note": "weights are fractions of Ark NAV; translate to Robinhood notional orders",
    }
    return out


def cmd_targets():
    out = compute()
    if "error" not in out:
        os.makedirs(STATE, exist_ok=True)
        tmp = TARGETS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(out, f, indent=1)
        os.replace(tmp, TARGETS_FILE)
    print(json.dumps(out, indent=1))


def cmd_weekly_check():
    """Mid-month exit: any CURRENT-TARGET holding whose LATEST price is >3% below
    its 10-month SMA gets flagged for exit to SGOV (spec: weekly check)."""
    try:
        with open(TARGETS_FILE) as f:
            targets = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(json.dumps({"error": "no ark2_targets.json — run targets first"}))
        return
    held = [s for s, w in targets.get("target_weights", {}).items()
            if s in UNIVERSE and w > 0]
    flags = []
    for s in held:
        r = fmp.indicators(s)
        if r.get("error"):
            flags.append({"symbol": s, "error": r["error"], "action": "DATA ERROR — no action"})
            continue
        sig = targets["signals"].get(s, {})
        sma = sig.get("sma10")
        price = r.get("price")
        if sma and price and price < sma * 0.97:
            flags.append({"symbol": s, "price": price, "sma10_monthend": sma,
                          "pct_below": round((price / sma - 1) * 100, 2),
                          "action": "EXIT to SGOV (broke 3% below 10-mo SMA mid-month)"})
    print(json.dumps({"as_of": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                      "held_checked": held, "flags": flags,
                      "all_clear": not flags}, indent=1))


def cmd_history():
    try:
        with open(HISTORY_FILE) as f:
            print(json.dumps(json.load(f), indent=1))
    except (FileNotFoundError, json.JSONDecodeError):
        print(json.dumps({"port_rets": [], "note": "no history yet"}))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "targets"
    if cmd == "targets":
        cmd_targets()
    elif cmd == "weekly-check":
        cmd_weekly_check()
    elif cmd == "history":
        cmd_history()
    else:
        print(json.dumps({"error": f"unknown command {cmd}"}))
        sys.exit(2)
