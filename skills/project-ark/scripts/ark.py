#!/usr/bin/env python3
"""
Project Ark — deterministic signal engine (multi-asset trend + dual-momentum rotation).

Mirrors backtests/ark_backtest.py EXACTLY (validated 2008-2026: 7.3% CAGR, -12.7% maxDD):
  FLOODGATE  crash override (SPY AND TLT < 10-mo SMA -> 100% SGOV); absolute momentum
             vs SGOV; 10% vol target on trailing 6 realized monthly portfolio returns
  TREND      eligible = month-end price > 10-month SMA AND 12-1 momentum > 0
  ROTATE     top 4 by blended 3/6/12-mo momentum, inverse-vol (12 monthly rets) weights
             scaled by filled/4, 40% class cap, residual -> SGOV

All monthly math uses MONTH-END closes of COMPLETED months (dividend-adjusted, FMP).
The engine only COMPUTES targets — it never places orders. The scheduled task translates
targets into Robinhood fractional notional orders (account 451480438 ONLY).

CLI:
  targets            compute + persist state/ark_targets.json, print summary
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

# symbol -> asset class (class cap 40%)
# SMH + XLE added 2026-08-16 after the universe gauntlet passed 5/5
# (backtests/ark_universe_gauntlet.py): +1.69 CAGR (7.32 -> 9.01), maxDD
# essentially unchanged (-12.67 -> -12.91), Sharpe 0.70 -> 0.80, better in 13 of
# 19 years and in 4/4 cap/top_n settings and 4/4 start dates.
# They are given their OWN asset classes deliberately: as "us_equity" the 40%
# class cap would force them to compete with VOO/IJR, which cut the gain to
# +0.68. They also do different jobs — SMH adds return but raises correlation to
# SPY (0.445 -> 0.510); XLE lowers it (-> 0.432) and turned 2022 from -3.9% to
# +0.1%. Together correlation lands at 0.485, barely above the original.
# CAVEAT: both were chosen in 2026 knowing semis/energy led this cycle, and the
# walk-forward gain concentrates in fold 3 (2020-2026, the AI boom). Expect a
# smaller live edge than backtested; the trend gate can and should reject them.
UNIVERSE = {
    "VOO": "us_equity", "IJR": "us_equity",
    "VEA": "intl_equity", "VWO": "intl_equity",
    "TLT": "treasuries", "VGIT": "treasuries",
    "LQD": "credit", "GLDM": "gold", "DBC": "commodities", "VNQ": "reits",
    "SMH": "semis", "XLE": "energy",
}
CASH = "SGOV"
BENCH = "SPY"
TOP_N = 4
CLASS_CAP = 0.40
VOL_TARGET = 0.10
TARGETS_FILE = os.path.join(STATE, "ark_targets.json")
HISTORY_FILE = os.path.join(STATE, "ark_history.json")


def month_end_series(sym):
    """{'YYYY-MM': last close of that month} from FMP daily bars (adjusted)."""
    d = fmp._get("historical-price-eod/full", {"symbol": sym, "limit": 500},
                 cache_key=f"ark:{sym}")
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
        print(json.dumps({"error": "no ark_targets.json — run targets first"}))
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
